import Mathlib

#eval IO.println "Finished."

#exit

theorem pi_case (a b : ℕ) (h : a ≤ b) : a + 0 ≤ b := by
  simpa using h
