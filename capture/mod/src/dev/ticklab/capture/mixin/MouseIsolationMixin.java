package dev.ticklab.capture.mixin;

import dev.ticklab.capture.TickProbe;
import net.minecraft.client.MouseHandler;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfo;

/** While a capture runs, mouse movement/buttons must not rotate the player or open menus. */
@Mixin(MouseHandler.class)
public abstract class MouseIsolationMixin {
    @Inject(method = {"onMove", "onButton", "onScroll"}, at = @At("HEAD"), cancellable = true, remap = false, require = 0)
    private void ticklab$isolate(CallbackInfo ci) { if (TickProbe.active()) ci.cancel(); }
}
