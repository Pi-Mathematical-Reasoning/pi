/-
A fixture in the layout of a miniF2F split file. Original statements only.
-/
import Mathlib

open scoped Nat
open scoped Real

/--
Add zero. -/
theorem fixture_add_zero (a : ℕ) : a + 0 = a := by
  sorry

theorem fixture_no_docstring (a b : ℕ) (h : a ≤ b) :
    a ≤ b + 1 := by
  sorry

/-- A comment sits between this docstring and its theorem. -/
-- a note the parser skips
theorem amc12a_2099_p1 (x : ℝ) (h₀ : x = 2) : x ^ 2 = 4 := by
  sorry

/- theorem fixture_commented_out (a : ℕ) : a = a := by
  sorry -/

theorem mathd_algebra_9001 (a : ℕ) :
    letI P : ℕ → Prop := fun n => n = n
    P a := by
  sorry

open scoped Polynomial in
theorem fixture_poly.variants.Polynomial (f : ℝ[X]) : f = f := by
  sorry

theorem mathd_numbertheory_9002 : 194 % 11 = 7 :=
  rfl

theorem fixture_tight_above (a : ℕ) : a = a := by
  sorry
/-- A docstring that follows a proof with no blank line.

It spans a blank line itself. -/
theorem fixture_tight_below (a : ℕ) : a ≤ a := by
  sorry
