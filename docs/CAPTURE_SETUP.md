# CAPTURE_SETUP — one-time Prism steps for the real-Minecraft capture

TickLab records real vanilla Minecraft 26.3 movement traces with a tiny Fabric client mod
(TickProbe, `capture/mod/`) running in a **dedicated** Prism Launcher instance. The agent builds and
installs the mod itself; it only needs you to do these one-time steps in Prism's UI. Your main
Minecraft instances are never touched (only an instance whose name contains `ticklab`).

1. **JDK 25** (needed to compile the mod). *Already satisfied on this laptop:* `javac 25.0.3` is on PATH.
   (Otherwise: `winget install EclipseAdoptium.Temurin.25.JDK`.)
2. In Prism Launcher create a **new instance named `ticklab-capture`**: Minecraft **26.3**, then
   Edit → Version → **Install Fabric Loader** (latest compatible; no Fabric API needed).
   Launch it once to the title screen and quit, so Prism downloads everything.
3. In that instance create a **singleplayer world named `ticklab`**
   (Superflat preset, "Allow commands/cheats" **ON**, difficulty **Peaceful**). Then quit the game.
4. Tell Claude nothing. When the file `CAPTURE_READY.md` appears in the project folder (the agent writes
   it after the mod is built and installed), click **Play** on `ticklab-capture` and open the `ticklab`
   world. The mod does the rest (≈ 33 scenarios × ~3 s) and closes the game when finished.
   The agent may ask for this twice (two batches in different orders, for the determinism check).

The agent polls for the instance every few minutes and keeps working on everything else meanwhile.
If anything here is impossible, write a line in `HUMAN_TODO.md` and the project continues in
"thin oracle" mode (clearly labeled everywhere).

Notes
- Never accept the Minecraft EULA or sign in on anyone's behalf: these steps are yours.
- Nothing from Prism (jars, worlds, saves) is committed to the repository.
