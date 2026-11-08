// Attachments: file picker, drag and drop, paste and screenshots.
import { $, status } from "./ui.mjs";

export function createUploads(ctx) {
  function renderUploads() {
    $("attachments").replaceChildren(
      ...ctx.uploads.map((item, index) => {
        const chip = document.createElement("div");
        chip.className = "attachment-chip";
        if (item.mime.startsWith("image/")) {
          const image = document.createElement("img");
          image.src = `data:${item.mime};base64,${item.data}`;
          image.alt = item.name;
          chip.append(image);
        }
        const name = document.createElement("span");
        name.textContent = item.name;
        chip.append(name);
        const remove = document.createElement("button");
        remove.textContent = "×";
        remove.ariaLabel = `Remove ${item.name}`;
        remove.onclick = () => {
          ctx.uploads.splice(index, 1);
          renderUploads();
        };
        chip.append(remove);
        return chip;
      }),
    );
  }
  async function addFiles(files) {
    if (ctx.captureBusy || ctx.controller) return;
    ctx.captureBusy = true;
    $("send").disabled = true;
    try {
      const pending = [];
      for (const file of files) {
        if (ctx.uploads.length + pending.length >= 8 || file.size > 4 * 1024 * 1024)
          throw new Error("Use at most eight files, each under 4 MB.");
        const data = await new Promise((resolve, reject) => {
          const reader = new FileReader();
          reader.onload = () => resolve(reader.result.split(",")[1]);
          reader.onerror = reject;
          reader.readAsDataURL(file);
        });
        pending.push({
          name: file.name,
          mime: file.type || "application/octet-stream",
          data,
          size: file.size,
        });
      }
      if (
        [...ctx.uploads, ...pending].reduce((sum, f) => sum + f.size, 0) >
        12 * 1024 * 1024
      )
        throw new Error("Attachments exceed 12 MB total.");
      ctx.uploads.push(...pending);
      renderUploads();
      status("Files attached to your next message.");
    } catch (error) {
      status(error.message || "Could not read attachment", true);
    } finally {
      ctx.captureBusy = false;
      $("send").disabled = Boolean(ctx.controller);
    }
  }
  $("upload").onclick = () => $("file-input").click();
  $("file-input").onchange = async () => {
    await addFiles($("file-input").files);
    $("file-input").value = "";
  };
  document.addEventListener("dragover", (event) => {
    event.preventDefault();
  });
  document.addEventListener("drop", async (event) => {
    event.preventDefault();
    await addFiles(event.dataTransfer.files);
  });
  $("screenshot").onclick = async () => {
    if (!ctx.extension) {
      status("Screenshot capture requires the installed Chrome extension.", true);
      return;
    }
    try {
      const image = await chrome.tabs.captureVisibleTab(
        ctx.sourceWindowId || undefined,
        { format: "jpeg", quality: 75 },
      );
      const bytes = Uint8Array.from(atob(image.split(",")[1]), (value) =>
        value.charCodeAt(0),
      );
      const file = new File([bytes], "Current page.jpg", { type: "image/jpeg" });
      await addFiles([file]);
      status("Screenshot attached. Review its thumbnail before sending.");
    } catch (error) {
      status(
        error.message +
          " Click the Shipit toolbar icon on the tab to grant access.",
        true,
      );
    }
  };
  document.addEventListener("paste", async (event) => {
    const files = [...(event.clipboardData?.files || [])];
    if (files.length) {
      event.preventDefault();
      await addFiles(files);
    }
  });
  return { renderUploads, addFiles };
}
