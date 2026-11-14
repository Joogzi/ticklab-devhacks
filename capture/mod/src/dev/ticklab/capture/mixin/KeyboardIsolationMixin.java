package dev.ticklab.capture.mixin;

import dev.ticklab.capture.TickProbe;
import net.minecraft.client.KeyboardHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** While a capture runs, physical key presses must not reach the game. */
@Mixin(KeyboardHandler.class)
public abstract class KeyboardIsolationMixin {
    @Inject(method = {"keyPress", "charTyped"}, at = @At("HEAD"), cancellable = true, remap = false, require = 0)
    private void ticklab$isolate(CallbackInfo ci) { if (TickProbe.active()) ci.cancel(); }
}
