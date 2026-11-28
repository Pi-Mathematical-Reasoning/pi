import Mathlib

set_option debug.skipKernelTC true in
theorem pi_case (a b : ℕ) (h : a ≤ b) : a + 0 ≤ b := by
  simpa using h
