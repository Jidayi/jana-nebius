---
name: acc-o-source-documents
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach source documents, books of prime entry, discounts and day book posting
description: "source documents, books of prime entry, day books, trade discount, cash discount: match each document to its book, work out the net amount and post the entries and totals. Not for: control accounts (acc-o-control-accounts) or the debit and credit rules (acc-o-double-entry)."
subject: accounting
levels: [O]
topics: [source documents, books of prime entry, day books, invoices, credit notes, trade discount, cash discount]
kcs:
  - kc.acc.o.source_documents.identify_source_document
  - kc.acc.o.source_documents.select_book_of_prime_entry
  - kc.acc.o.source_documents.trade_discount
  - kc.acc.o.source_documents.cash_discount
  - kc.acc.o.source_documents.post_day_book_totals
curriculum_refs: [ACC-O-02]
prerequisites:
  - kc.acc.o.accounting_equation.purpose_and_users
  - kc.acc.o.double_entry.record_credit_transactions
related: [acc-o-control-accounts, acc-o-double-entry]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, math_evaluate]
visuals: [t_account]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: trade_discount_rate
    unit: percent
    min: 0
    max: 50
    context: trade discount given by a wholesaler or supplier to a trade customer
  - quantity: cash_discount_rate
    unit: percent
    min: 0
    max: 10
    context: cash discount offered for paying an invoice within the stated period
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student names the source document and the book of prime entry for a transaction
  - The student works out the amount after trade discount and the cash discount on that amount
  - The student states which ledger accounts receive each day book entry and the day book total, and on which side
---

# Source documents and books of prime entry

## When to use

Use when a question asks which document records a transaction, which day book or journal it is first written in,
the amount after trade discount, the cash discount and the amount paid, or how day book entries and totals reach
the ledger.

Not for: control accounts (acc-o-control-accounts) or the debit and credit rules on their own (acc-o-double-entry).

## What this skill does not do

- It does not teach the layout of business documents beyond the facts that decide the entry.
- It does not balance ledger accounts or prepare a trial balance.
- It does not compute discounts itself: the question gives the rates and the tools give the amounts.

## Objectives

1. The student names the source document and the book of prime entry for a transaction.
2. The student works out the amount after trade discount and the cash discount on that amount.
3. The student states which ledger accounts receive each day book entry and the day book total, and on which side.

## Prerequisite probe

- "Goods are sold today and the customer will pay next month. Is this a cash sale or a credit sale?" Expected: a credit sale.
- "What is 10% of 600?" Expected: 60 (checked with math_evaluate).

If the first fails, detour to recording credit transactions; if the second fails, practise percentages first.

## Teaching sequence

1. Ask what happened: a sale, a purchase or a return; goods for resale or something else; cash or credit. Done when the student states all three features.
2. Ask which document records it and who issues it. Done when the student names one document and its issuer.
3. Ask which book of prime entry first records it, and why that book. Done when the student names one book with a reason.
4. For trade discount, ask for the discount and the net amount; the math_evaluate result is the reference value. Done when the student's net amount matches the checked value.
5. For cash discount, ask which amount it applies to, then for the discount and the amount paid; math_evaluate gives the reference values. Done when both figures match the checked values.
6. Ask where each day book entry and the day book total go in the ledger; acc_double_entry checks the posting. Done when the tool reports the posting balanced with every line ok.

## Hint ladder

1. Orient: "Did money change hands at the time, and were goods sent or sent back?"
2. Concept: day books hold credit sales, credit purchases of goods for resale and returns; the cash book holds money; the general journal holds the rest.
3. First step: name the document and ask which book it is copied into.
4. Worked step: show the trade discount taken off the list price and ask for the cash discount on what is left.
5. Full step: show the checked amounts and the posting; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.sd_receipt_invoice_confused`: thinks a credit sale gets a receipt → "Has any money been paid yet when goods are sold on credit?"
- `mc.acc.o.sd_invoice_credit_note_confused`: swaps invoice and credit note → "Does this document ask for money, or reduce what is owed?"
- `mc.acc.o.sd_counterfoil_vs_paying_in`: swaps cheque counterfoil and paying-in slip → "Did this money leave the bank account or go into it?"
- `mc.acc.o.sd_cash_sales_in_sales_journal`: puts cash sales in the sales journal → "After a cash sale, is any customer left owing money?"
- `mc.acc.o.sd_asset_credit_in_purchases_journal`: puts a van bought on credit in the purchases journal → "Is the van bought to sell to customers, or to keep and use?"
- `mc.acc.o.sd_returns_journal_confused`: uses the wrong returns journal → "Who sent the goods back, a customer or the business itself?"
- `mc.acc.o.sd_discount_amount_as_net`: gives the discount instead of the net amount → "Is that what the customer is invoiced for, or the amount taken off?"
- `mc.acc.o.sd_trade_discount_recorded`: enters the list price in the books → "Does trade discount ever reach the ledger, or only the invoice?"
- `mc.acc.o.sd_cash_discount_on_list_price`: takes cash discount on the list price → "The invoice already shows the price after trade discount. Which amount does the customer owe?"
- `mc.acc.o.sd_discount_as_payment`: gives the cash discount as the amount paid → "Is the cash discount what the customer pays, or what the customer saves?"
- `mc.acc.o.sd_double_posting`: credits sales with each invoice and again with the total → "If each invoice and then the total are both credited to sales, how many times is each sale counted?"

## Confidence and escalation

- Two wrong books in a row: switch to a three-question sort (money now or later, goods for resale or not, out or back).
- Three failures on discounts: detour to percentages of an amount, then return.
- A local document the pack does not name: save it as a question for a teacher.

## Worked exchange

> Tutor: Goods with a list price of 2,000 are sold on credit with 20% trade discount and 5% cash discount for payment within 14 days. The customer pays in time. What goes in the sales journal, and how much does the customer pay?
> Student: Trade discount is 400, so 1,600 goes in the sales journal.
> Tutor: Good. Now the cash discount: what is it?
> Student: 5% of 2,000, so 100.
> Tutor: After the invoice, how much does the customer owe?
> Student: 1,600. So the discount is 5% of 1,600, which is 80, and the customer pays 1,520.
> Tutor: Right: 1,520 received and 80 discount allowed (checked with the maths tool).

## Verification checklist

- Trade discount never appears in the ledger; the day book shows the net amount.
- Cash discount is worked on the net amount, and only when payment is within the period.
- Every amount came from math_evaluate and is shown to 2 decimal places when it has cents.
- The posting passed acc_double_entry: personal accounts take each entry, the nominal account takes the total once.
