JP SPA - Correct existing employee salary (2026-11-18)
=======================================================
Use ONLY this incremental patch. Do not overwrite your current project/admin.py.

This package is built against the last admin_employee_detail.html supplied here
(JP_SPA_admin_employee_detail_updated.html) and a pre-existing salary route.

At the project root:
  git apply --check path\to\salary_history_edit_only.patch
  git apply path\to\salary_history_edit_only.patch

If the full patch does not apply because you customized your HTML:
  git apply --check path\to\admin_salary_route_only.patch
  git apply path\to\admin_salary_route_only.patch
  BACK UP your own employee detail HTML, compare before using the provided
  full admin_employee_detail.html. Do not blindly overwrite customization.

Validation:
  python -m py_compile project/admin.py
  git diff --check
  git diff -- project/admin.py project/templates/admin_employee_detail.html
  Test in staging as Admin: open an existing monthly salary, edit amounts,
  confirm correct total and no additional monthly row. Test repeat correction,
  missing month, unauthorized Staff, CSRF, and nonexistent employee.

IMPORTANT:
The supplied 2026-11-18 SQL snapshot does NOT contain employee_salaries.
The actual online DB schema is unverified. This patch requires the existing
employee_salaries table and its documented fields. It does not add tables,
change salary formula, or touch other functionality.
