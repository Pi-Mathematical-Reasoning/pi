import Mathlib

theorem pi_case' (a b : ℕ) (h : a ≤ b) : a + 0 ≤ b := by
  simpa using h
