import { invoke } from "@tauri-apps/api/core";
import { Store } from "@tauri-apps/plugin-store";
import type { Response, Cache } from "$lib/types";
import { get } from "svelte/store";
import {
  serverUrl,
  emails,
  currentFolder,
  folders,
  currentOffset,
  accounts,
} from "$lib/stores";

let serverConnectionTryCount = 0;
async function initServer(url: string) {
  if (serverConnectionTryCount > 5) {
    throw new Error("There was an error connecting to the server!");
    return;
  }

  try {
    serverConnectionTryCount++;
    const response: Response = await fetch(`${url}/hello`).then((res) =>
      res.json(),
    );
    if (response.success) {
      serverUrl.set(url);
      return;
    }
  } catch {
    setTimeout(async () => {
      await getServerURL();
    }, 2000);
  }
}

async function getServerURL() {
  if (get(serverUrl).length > 0)
    return;

  await invoke("get_server_url").then(async (url) => {
    await initServer(url as string);
  });
}

async function loadData() {
  const store = new Store("openmail_cache.bin");
  const cache: Cache | null = await store.get("cache");
  if (cache) {
    accounts.set(cache["accounts"]);
    emails.set(cache["emails"]);
    currentFolder.set(cache["currentFolder"]);
    folders.set(cache["folders"]);
    currentOffset.set(cache["currentOffset"]);
    // TODO: Get \\NEW emails and update emails and save date again
  }
}

export const load = async () => {
  await getServerURL();
  await loadData();
};
