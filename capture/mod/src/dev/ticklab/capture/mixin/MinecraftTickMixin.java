package dev.ticklab.capture.mixin;

import dev.ticklab.capture.TickProbe;
import net.minecraft.client.Minecraft;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** Scripted input at the start of each client tick; sampling at its end. */
@Mixin(Minecraft.class)
public abstract class MinecraftTickMixin {
    @Inject(method = "tick", at = @At("HEAD"), remap = false)
    private void ticklab$head(CallbackInfo ci) { TickProbe.head((Minecraft) (Object) this); }

    @Inject(method = "tick", at = @At("TAIL"), remap = false)
    private void ticklab$tail(CallbackInfo ci) { TickProbe.tail((Minecraft) (Object) this); }
}
