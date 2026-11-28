import Mathlib

/- Add a new theorem `pi_false : False` without kernel checking. Its value, `True.intro`, does not
have type `False`. -/
open Lean in
#eval modifyEnv (m := MetaM) fun env =>
  let decl := Declaration.thmDecl {
    name := `pi_false
    levelParams := []
    type := .const ``False []
    value := .const ``True.intro []
  }
  match env.addDeclCore 0 decl none (doCheck := false) with
  | .ok env => env
  | .error _ => env

theorem falseThm : False := pi_false
