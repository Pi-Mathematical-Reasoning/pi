import Mathlib

theorem efsq : ∀ (x y z n : Nat),
    0 < x → 0 < y → 0 < z → 2 < n →
    x^n + y^n ≠ z^n := by
  sorry
-- Adapted from SafeVerify at b291b588a53999a7e837dda61c7dbfe8c550c814, SafeVerifyTest/ReplaceAxiom/Target.lean (Apache-2.0): import Mathlib is added as its first line.
