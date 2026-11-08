// Developer smoke runner for Playwright's browser_run_code tool.
// Supply { extensionPath, executablePath, token } when invoking this function.
// Uses an isolated Chrome profile and real bridge calls.
async (page, { extensionPath, executablePath, token, screenshotPath }) => {
  const context = await page
    .context()
    .browser()
    .browserType()
    .launchPersistentContext("", {
      executablePath,
      headless: true,
      args: [
        `--disable-extensions-except=${extensionPath}`,
        `--load-extension=${extensionPath}`,
      ],
    });
  try {
    const worker =
      context.serviceWorkers()[0] ||
      (await context.waitForEvent("serviceworker"));
    const panel = await context.newPage();
    const errors = [];
    panel.on("pageerror", (error) => errors.push(error.message));
    await panel.setViewportSize({ width: 370, height: 620 });
    await panel.goto(
      `chrome-extension://${new URL(worker.url()).host}/sidepanel.html`,
    );
    await panel.locator("#settings").click();
    await panel.locator("#token").fill(token);
    await panel.locator("#connect-button").click();
    await panel.locator("#config").waitFor({ state: "hidden" });
    const results = [];
    async function send(prompt) {
      await panel.locator("#prompt").fill(prompt);
      const pending = panel.waitForResponse((response) =>
        response.url().endsWith("/chat"),
      );
      await panel.locator("#send").click();
      const response = await pending;
      await panel.waitForFunction(
        () => {
          const status = document.querySelector("#status");
          return (
            status.textContent === "Complete" ||
            status.classList.contains("error")
          );
        },
        {},
        { timeout: 45000 },
      );
      const result = {
        httpStatus: response.status(),
        status: await panel.locator("#status").innerText(),
        answer: await panel.locator(".assistant .body").last().innerText(),
      };
      results.push(result);
      if (result.status !== "Complete") throw new Error(JSON.stringify(result));
      await panel.locator("#stop").waitFor({ state: "hidden" });
    }
    await panel.locator("#file-input").setInputFiles({
      name: "apollo.txt",
      mimeType: "text/plain",
      buffer: Buffer.from(
        "Project Apollo owner: Mira. Deadline: 14 October. Budget: 12000 EUR.",
      ),
    });
    await send(
      "Read the attached project note. Tell me its owner, deadline and budget in one sentence.",
    );
    await send(
      "Move the deadline in our conversation to 21 October. Who is the owner and what is the updated deadline? One sentence.",
    );
    await panel.locator("#model").selectOption("google.gemma-4-26b-a4b");
    await send(
      "What is the revised deadline and original project budget? One sentence, using our earlier conversation.",
    );
    if (
      !/Mira/.test(results[0].answer) ||
      !/21/.test(results[1].answer) ||
      !/21/.test(results[2].answer) ||
      !/12[,.]?000/.test(results[2].answer)
    )
      throw new Error(
        "The live answers did not retain the expected project facts",
      );
    await panel.reload();
    await panel
      .locator("#connection")
      .filter({ hasText: "Agent connected" })
      .waitFor();
    if (
      (await panel.locator(".assistant").count()) !== 3 ||
      (await panel.locator("#model").inputValue()) !== "google.gemma-4-26b-a4b"
    )
      throw new Error("Reload did not preserve transcript and selected model");
    await panel.locator("#settings").click();
    await panel
      .locator("#token")
      .fill("invalid-bridge-token-for-recovery-test");
    await panel.locator("#connect-button").click();
    await panel
      .locator("#config-status")
      .filter({ hasText: "Invalid bridge token" })
      .waitFor();
    await panel.locator("#cancel-config").click();
    if ((await panel.locator(".assistant").count()) !== 3)
      throw new Error("A failed connection cleared the transcript");
    const sizes = [];
    for (const [width, height] of [
      [320, 500],
      [410, 900],
      [1100, 740],
    ]) {
      await panel.setViewportSize({ width, height });
      sizes.push(
        await panel.evaluate(() => ({
          width: innerWidth,
          height: innerHeight,
          documentOverflow: document.documentElement.scrollHeight > innerHeight,
          horizontalOverflow: document.documentElement.scrollWidth > innerWidth,
          composerBottom: document
            .querySelector(".compose-zone")
            .getBoundingClientRect().bottom,
        })),
      );
    }
    if (
      sizes.some(
        (size) =>
          size.documentOverflow ||
          size.horizontalOverflow ||
          size.composerBottom > size.height,
      )
    )
      throw new Error("The composer does not fit its viewport");
    if (errors.length) throw new Error(errors.join("\n"));
    if (screenshotPath) {
      await panel.setViewportSize({ width: 370, height: 740 });
      await panel.emulateMedia({ colorScheme: "dark" });
      await panel.screenshot({ path: screenshotPath });
    }
    return {
      results,
      sizes,
      reloadPreservedChat: true,
      failedConnectionPreservedChat: true,
      errors,
    };
  } finally {
    await context.close();
  }
};
