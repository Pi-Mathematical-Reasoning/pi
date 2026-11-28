import Mathlib

theorem pi_case (x y : ℕ) (hxy : x ≤ y) : x + 0 ≤ y := by
  simpa using hxy
