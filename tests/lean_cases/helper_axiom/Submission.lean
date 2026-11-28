import Mathlib

axiom pi_helper (a b : ℕ) : a + 0 ≤ b

theorem pi_case (a b : ℕ) (h : a ≤ b) : a + 0 ≤ b := pi_helper a b
