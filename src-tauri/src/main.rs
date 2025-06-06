// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod consts;
mod utils;

use chrono::Local;
use std::env;
use std::fs;
use std::fs::OpenOptions;
use std::io::Write;
use std::process::Command;
use tauri::{Manager, RunEvent};

struct ServerInfo {
    url: String,
    pid: u32,
}

fn start_uvicorn() -> Result<(), String> {
    if consts::IS_WINDOWS {
        Command::new("cmd")
            .current_dir("src/script")
            .arg("/C")
            .arg(consts::UVICORN_START_SCRIPT_PATH)
            .spawn()
            .map_err(|err| format!("Failed to start Python server: {}", err))?;
    } else {
        Command::new("sh")
            .current_dir("src/script")
            .arg("-c")
            .arg(consts::UVICORN_START_SCRIPT_PATH)
            .spawn()
            .map_err(|err| format!("Failed to start Python server: {}", err))?;
    }
    Ok(())
}

fn kill_uvicorn(pid: u32) -> Result<(), String> {
    if consts::IS_WINDOWS {
        Command::new("taskkill")
            .arg("/PID")
            .arg(pid.to_string())
            .arg("/F")
            .status()
            .map_err(|err| format!("Failed to kill process: {}", err))?;
    } else {
        Command::new("kill")
            .arg("-TERM")
            .arg(pid.to_string())
            .status()
            .map_err(|err| format!("Failed to kill process: {}", err))?;
    }

    add_close_log(&pid.to_string())?;

    Ok(())
}

fn add_close_log(pid: &str) -> Result<(), String> {
    // Since we are closing the app by killing the process from terminal directly,
    // we need to manually add a log entry to the log file to indicate that the server
    // was stopped by closing the app. If you think there is a better way to handle this,
    // please feel free to make a PR because I don't like this "solution".
    let now = Local::now();
    let level = "INFO";
    let message = format!("Server stopped by closing the application | PID: {}", pid);
    let log_entry = format!(
        "{} - {} - {}\n",
        now.format("%Y-%m-%d %H:%M:%S,%3f"),
        level,
        message
    );

    let mut file = OpenOptions::new()
        .append(true)
        .create(true)
        .open(utils::build_home_path(consts::UVICORN_LOG_FILE_PATH))
        .map_err(|err| format!("Failed to open log file: {}", err))?;

    file.write_all(log_entry.as_bytes())
        .map_err(|err| format!("Failed to write to log file: {}", err))?;

    Ok(())
}

fn read_uvicorn_info_file() -> Result<ServerInfo, String> {
    let uvicorn_info = fs::read_to_string(utils::build_home_path(consts::UVICORN_INFO_FILE_PATH))
        .map_err(|err| format!("Failed to read PID file: {}", err))?;
    let uvicorn_info: Vec<&str> = uvicorn_info.split('\n').collect();
    let url = uvicorn_info[0].split('=').collect::<Vec<&str>>()[1].to_string();
    let pid = uvicorn_info[1].split('=').collect::<Vec<&str>>()[1]
        .parse::<u32>()
        .map_err(|err| format!("Invalid PID: {}", err))?;
    Ok(ServerInfo { url, pid })
}

fn remove_uvicorn_info_file() -> Result<(), String> {
    fs::remove_file(utils::build_home_path(consts::UVICORN_INFO_FILE_PATH))
        .map_err(|err| format!("Failed to remove INFO file: {}", err))
}

#[tauri::command]
fn get_server_url() -> String {
    read_uvicorn_info_file().unwrap().url
}

fn main() {
    let mut builder = tauri::Builder::default();

    #[cfg(desktop)]
    {
        builder = builder.plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                window.set_focus().ok();
            } else {
                println!("Main window not found");
            }
        }));
    }

    builder
        .plugin(tauri_plugin_autostart::Builder::new().build())
        .plugin(tauri_plugin_os::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .invoke_handler(tauri::generate_handler![get_server_url])
        .build(tauri::generate_context!())
        .expect("Error building app")
        .run(move |_app_handle, event| match event {
            RunEvent::Ready => {
                start_uvicorn().ok();
            }
            RunEvent::ExitRequested { api, .. } => {
                api.prevent_exit();
                if let Ok(info) = read_uvicorn_info_file() {
                    if let Ok(_) = kill_uvicorn(info.pid) {
                        remove_uvicorn_info_file().ok();
                    }
                }
                std::process::exit(0);
            }
            _ => {}
        });
}
