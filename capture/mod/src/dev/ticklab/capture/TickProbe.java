package dev.ticklab.capture;

import com.google.gson.JsonArray;
import com.google.gson.JsonElement;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import java.io.IOException;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Random;
import net.fabricmc.loader.api.FabricLoader;
import net.minecraft.client.Minecraft;
import net.minecraft.client.player.LocalPlayer;
import net.minecraft.server.MinecraftServer;
import net.minecraft.world.phys.Vec3;

/**
 * TickLab capture: drives scripted key input at the HEAD of Minecraft#tick and samples the local player
 * at the TAIL. Record i = state after scenario tick i (PROJECT.md section 4.3).
 */
public final class TickProbe {
    public static final String VERSION = "0.1.0";
    private static final double SETTLED_VY = -0.0784000015258789;
    private enum Phase { LOAD, WAIT_WORLD, SETUP, RESET, SETTLE, RUN, DONE, OFF }

    private static Phase phase = Phase.LOAD;
    private static JsonObject cfg;
    private static Path outDir;
    private static final List<JsonObject> queue = new ArrayList<>();
    private static int qi = 0, wait = 0, tick = 0, retries = 0, headTickCount = -1;
    private static boolean headApplied = false;
    private static JsonObject cur;
    private static String curFile;
    private static StringBuilder buf;
    private static final JsonArray failures = new JsonArray();
    private static final JsonArray timings = new JsonArray();
    private static long startedAt, scenarioStart;

    /** Physical input is blocked only while the capture drives the player inside the world (never on menus). */
    public static boolean active() { return phase == Phase.SETUP || phase == Phase.RESET || phase == Phase.SETTLE || phase == Phase.RUN; }

    public static void head(Minecraft mc) {
        try {
            if (phase == Phase.LOAD) load(mc);
            if (phase == Phase.OFF || phase == Phase.DONE) return;
            mc.options.pauseOnLostFocus = false;
            headApplied = false;
            LocalPlayer p = mc.player;
            if (p == null || mc.level == null || !mc.hasSingleplayerServer() || mc.isPaused()) return;
            headTickCount = p.tickCount;
            headApplied = true;
            if (phase == Phase.RUN) applyInputs(mc, p, tick);
            else releaseKeys(mc);
        } catch (Throwable t) { fail("head", t); }
    }

    public static void tail(Minecraft mc) {
        try {
            if (phase == Phase.OFF || phase == Phase.DONE || phase == Phase.LOAD) return;
            LocalPlayer p = mc.player;
            if (p == null || mc.level == null || !mc.hasSingleplayerServer()) return;
            if (!headApplied || p.tickCount == headTickCount) return; // the player did not tick this frame
            switch (phase) {
                case WAIT_WORLD -> { if (mc.gui.screen() == null) { phase = Phase.SETUP; wait = 0; } }
                case SETUP -> setup(mc);
                case RESET -> reset(p);
                case SETTLE -> settle(mc, p);
                case RUN -> run(mc, p);
                default -> { }
            }
        } catch (Throwable t) { fail("tail", t); }
    }

    private static void load(Minecraft mc) throws IOException {
        Path gameDir = FabricLoader.getInstance().getGameDir();
        Path cp = gameDir.resolve("config").resolve("ticklab_capture.json");
        if (!Files.exists(cp)) { phase = Phase.OFF; return; }
        cfg = JsonParser.parseString(Files.readString(cp, StandardCharsets.UTF_8)).getAsJsonObject();
        if (!cfg.has("enabled") || !cfg.get("enabled").getAsBoolean()) { phase = Phase.OFF; return; }
        outDir = Path.of(cfg.get("out_dir").getAsString());
        Files.createDirectories(outDir);
        Files.deleteIfExists(outDir.resolve("done.json"));
        JsonArray all = JsonParser.parseString(Files.readString(Path.of(cfg.get("scenarios_file").getAsString()),
                StandardCharsets.UTF_8)).getAsJsonObject().getAsJsonArray("scenarios");
        List<String> only = names(cfg, "only");
        for (JsonElement e : all) {
            JsonObject s = e.getAsJsonObject().has("scenario") ? e.getAsJsonObject().getAsJsonObject("scenario") : e.getAsJsonObject();
            if (only.isEmpty() || only.contains(s.get("name").getAsString())) queue.add(s);
        }
        String order = cfg.has("order") ? cfg.get("order").getAsString() : "listed";
        if (order.equals("reversed")) Collections.reverse(queue);
        if (order.equals("shuffled")) Collections.shuffle(queue, new Random(cfg.has("seed") ? cfg.get("seed").getAsLong() : 1L));
        for (String n : names(cfg, "repeat_check"))
            for (JsonObject s : new ArrayList<>(queue))
                if (s.get("name").getAsString().equals(n)) { JsonObject c = s.deepCopy(); c.addProperty("_repeat", true); queue.add(c); }
        mc.options.autoJump().set(false);
        mc.options.toggleSprint().set(false);
        mc.options.toggleCrouch().set(false);
        startedAt = System.currentTimeMillis();
        phase = Phase.WAIT_WORLD;
    }

    private static List<String> names(JsonObject o, String key) {
        List<String> out = new ArrayList<>();
        if (o.has(key)) for (JsonElement e : o.getAsJsonArray(key)) out.add(e.getAsString());
        return out;
    }

    private static void command(Minecraft mc, String c) {
        MinecraftServer srv = mc.getSingleplayerServer();
        srv.executeIfPossible(() -> srv.getCommands().performPrefixedCommand(srv.createCommandSourceStack().withSuppressedOutput(), c));
    }

    private static void setup(Minecraft mc) {
        if (wait == 0) {
            String[] cmds = {"gamemode survival @a", "difficulty peaceful", "time set noon", "weather clear", "effect clear @a",
                "gamerule doDaylightCycle false", "gamerule doWeatherCycle false", "gamerule doMobSpawning false",
                "gamerule advance_time false", "gamerule advance_weather false", "gamerule spawn_mobs false",
                "fill -48 99 -48 48 99 48 minecraft:stone"};
            for (String c : cmds) command(mc, c);
            for (int y = 100; y <= 120; y++) command(mc, "fill -48 " + y + " -48 48 " + y + " 48 minecraft:air");
            command(mc, "tp @a 0.5 100 0.5 0 0");
        }
        if (++wait >= 60) { phase = Phase.RESET; wait = 0; }
    }

    private static void releaseKeys(Minecraft mc) {
        mc.options.keyUp.setDown(false); mc.options.keyDown.setDown(false); mc.options.keyLeft.setDown(false);
        mc.options.keyRight.setDown(false); mc.options.keyJump.setDown(false); mc.options.keyShift.setDown(false);
        mc.options.keySprint.setDown(false);
    }

    private static void reset(LocalPlayer p) {
        if (qi >= queue.size()) { finish(); return; }
        cur = queue.get(qi);
        p.setSprinting(false);
        p.setPos(0.5, 100.0, 0.5);
        p.setYRot(0f); p.setXRot(0f); p.yRotO = 0f; p.xRotO = 0f;
        p.setDeltaMovement(Vec3.ZERO);
        wait = cfg.has("settle_ticks") ? cfg.get("settle_ticks").getAsInt() : 30;
        phase = Phase.SETTLE;
    }

    private static void settle(Minecraft mc, LocalPlayer p) throws IOException {
        if (--wait > 0) return;
        Vec3 v = p.getDeltaMovement();
        boolean ok = p.onGround() && Math.abs(v.x) < 1e-9 && Math.abs(v.z) < 1e-9 && Math.abs(v.y - SETTLED_VY) < 1e-12
                && !p.isSprinting() && !p.isCrouching() && p.getY() == 100.0 && p.getX() == 0.5 && p.getZ() == 0.5;
        if (!ok) {
            if (retries++ < 1) { phase = Phase.RESET; return; }
            JsonObject f = new JsonObject(); f.addProperty("name", cur.get("name").getAsString());
            f.addProperty("reason", "not settled: " + state(p, "initial", -1)); failures.add(f);
            retries = 0; qi++; phase = Phase.RESET; return;
        }
        retries = 0;
        boolean rep = cur.has("_repeat");
        curFile = cur.get("name").getAsString() + (rep ? ".repeat" : "") + ".raw.jsonl";
        buf = new StringBuilder();
        buf.append(state(p, "initial", -1)).append('\n');
        tick = 0;
        scenarioStart = System.currentTimeMillis();
        phase = Phase.RUN;
    }

    private static void applyInputs(Minecraft mc, LocalPlayer p, int t) {
        boolean[] k = new boolean[7];
        String[] names = {"forward", "backward", "left", "right", "jump", "shift", "sprint"};
        for (JsonElement e : cur.getAsJsonArray("actions")) {
            JsonObject a = e.getAsJsonObject();
            int at = a.get("at").getAsInt();
            if (at > t) continue;
            if (a.has("key")) {
                for (int i = 0; i < 7; i++) if (names[i].equals(a.get("key").getAsString())) k[i] = a.get("down").getAsBoolean();
            } else if (at == t) {
                if (a.has("yaw")) { p.setYRot(a.get("yaw").getAsFloat()); p.yRotO = p.getYRot(); }
                if (a.has("pitch")) { p.setXRot(a.get("pitch").getAsFloat()); p.xRotO = p.getXRot(); }
            }
        }
        mc.options.keyUp.setDown(k[0]); mc.options.keyDown.setDown(k[1]); mc.options.keyLeft.setDown(k[2]);
        mc.options.keyRight.setDown(k[3]); mc.options.keyJump.setDown(k[4]); mc.options.keyShift.setDown(k[5]);
        mc.options.keySprint.setDown(k[6]);
    }

    private static void run(Minecraft mc, LocalPlayer p) throws IOException {
        buf.append(state(p, "tick", tick)).append('\n');
        if (++tick < cur.get("duration").getAsInt()) return;
        releaseKeys(mc);
        Files.writeString(outDir.resolve(curFile), buf.toString(), StandardCharsets.UTF_8);
        JsonObject tm = new JsonObject(); tm.addProperty("name", curFile); tm.addProperty("ms", System.currentTimeMillis() - scenarioStart);
        timings.add(tm);
        qi++;
        JsonObject prog = new JsonObject(); prog.addProperty("done", qi); prog.addProperty("total", queue.size());
        prog.addProperty("last", curFile);
        Files.writeString(outDir.resolve("progress.json"), prog.toString(), StandardCharsets.UTF_8);
        phase = Phase.RESET;
    }

    static String state(LocalPlayer p, String type, int t) {
        Vec3 v = p.getDeltaMovement();
        StringBuilder s = new StringBuilder("{\"type\":\"").append(type).append('"');
        if (t >= 0) s.append(",\"tick\":").append(t);
        s.append(",\"x\":").append(p.getX()).append(",\"y\":").append(p.getY()).append(",\"z\":").append(p.getZ())
         .append(",\"vx\":").append(v.x).append(",\"vy\":").append(v.y).append(",\"vz\":").append(v.z)
         .append(",\"on_ground\":").append(p.onGround()).append(",\"yaw\":").append((double) p.getYRot())
         .append(",\"pitch\":").append((double) p.getXRot()).append(",\"pose\":\"").append(p.getPose().name()).append('"')
         .append(",\"sprinting\":").append(p.isSprinting()).append(",\"sneaking\":").append(p.isCrouching())
         .append(",\"horizontal_collision\":").append(p.horizontalCollision).append('}');
        return s.toString();
    }

    private static void finish() {
        phase = Phase.DONE;
        try {
            Minecraft mc = Minecraft.getInstance();
            JsonObject d = new JsonObject();
            d.addProperty("mod", "ticklab_capture " + VERSION);
            d.addProperty("minecraft", mc.getLaunchedVersion());
            d.addProperty("java", System.getProperty("java.version"));
            d.addProperty("order", cfg.has("order") ? cfg.get("order").getAsString() : "listed");
            d.addProperty("scenarios", queue.size());
            d.addProperty("captured", timings.size());
            d.add("failures", failures);
            d.add("timings", timings);
            d.addProperty("elapsed_ms", System.currentTimeMillis() - startedAt);
            Files.writeString(outDir.resolve("done.json"), d.toString(), StandardCharsets.UTF_8);
            if (!cfg.has("quit_when_done") || cfg.get("quit_when_done").getAsBoolean()) mc.stop();
        } catch (Throwable t) { fail("finish", t); }
    }

    private static void fail(String where, Throwable t) {
        phase = Phase.DONE;
        try {
            if (outDir != null) {
                JsonObject d = new JsonObject(); d.addProperty("error", where + ": " + t);
                d.add("failures", failures); d.addProperty("captured", timings.size());
                Files.writeString(outDir.resolve("done.json"), d.toString(), StandardCharsets.UTF_8);
            }
        } catch (IOException ignored) { }
        t.printStackTrace();
    }
}
