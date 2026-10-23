# Principles of Accounts, O level

Our own curriculum map for O level Principles of Accounts (CUR-02): 17 topics and 78 knowledge components that cover
the common body of O level accounting syllabuses, written in our own words. No board's syllabus text, past paper or
textbook text is used (D35). Topic exam weights are estimates of a typical paper's share of marks for the subject lead
to confirm (CUR-03).

Every record was drafted with AI (its provenance says so) and enters the pipeline as `verified` only after the build's
tools reproduce every key and every number in its hints and solutions (CUR-20). Keys are exact money at 2 decimal
places; each item's `checks:` also run the accounting checker its KC names (`acc_double_entry`, `acc_statements`,
`acc_depreciation`, `acc_inventory`, `acc_ratios`, `acc_break_even`). Teacher review follows (CUR-21, D65).

Board-specific choices are pack conventions (CUR-28), in `../../ref/acc-o/conventions.yaml`, never hard-coded:

- currency `$` and 2 decimal places, rounded half away from zero;
- chart of accounts `coa.acc.o.standard.v1`; its accounts travel in each checker call's arguments (G103);
- statement of financial position layout, bank reconciliation start, part-year depreciation and AVCO rounding;
- the ratio definition set (`acc.definition_set.*`): a 365-day year, capital employed as capital plus non-current
  liabilities at the year end, average inventory, credit sales and credit purchases for the collection periods, and
  the acid-test ratio without inventory;
- terms with their synonyms (balance sheet, debtors, creditors, stock, bad debts, net profit, and so on).
