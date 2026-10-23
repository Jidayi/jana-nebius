---
name: mth-o-statistics
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach averages, spread, tables and statistical charts from raw or grouped data
description: "statistics, mean, median, mode, range, frequency tables, pie charts, scatter diagrams, cumulative frequency, histograms: read the data, use every frequency, check the size. Not for: probability (mth-o-probability) or line equations (mth-o-coordinate-geometry)."
subject: mathematics
levels: [O]
topics: [statistics, averages, frequency tables, pie charts, scatter diagrams, cumulative frequency, histograms, types of data]
kcs:
  - kc.mth.o.statistics.data_types
  - kc.mth.o.statistics.read_tables
  - kc.mth.o.statistics.averages_list
  - kc.mth.o.statistics.averages_frequency
  - kc.mth.o.statistics.grouped_mean
  - kc.mth.o.statistics.pie_charts
  - kc.mth.o.statistics.scatter_correlation
  - kc.mth.o.statistics.cumulative_frequency
  - kc.mth.o.statistics.histograms
curriculum_refs: [MTH-O-09.01, MTH-O-09.02, MTH-O-09.03, MTH-O-09.04, MTH-O-09.05, MTH-O-09.06, MTH-O-09.07]
prerequisites:
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.number.direct_proportion
  - kc.mth.o.coordinate_geometry.line_equation
related: [mth-o-probability, mth-o-coordinate-geometry]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, stats_compute]
visuals: [statistics_chart, matrix_table]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: mean
    unit: dimensionless
    min: -100
    max: 100000
    context: averages of marks, counts, heights, masses and temperatures in school data sets
  - quantity: median
    unit: dimensionless
    min: -100
    max: 100000
    context: middle values of lists, frequency tables and cumulative frequency curves
  - quantity: interquartile_range
    unit: dimensionless
    min: 0
    max: 100000
    context: spread between the quartiles of a school data set
  - quantity: angle
    unit: degree
    min: 0
    max: 360
    context: sector angles of pie charts
  - quantity: frequency
    unit: dimensionless
    min: 0
    max: 100000
    context: counts in tables, pie chart sectors and histogram classes
  - quantity: frequency_density
    unit: dimensionless
    min: 0
    max: 10000
    context: frequency divided by class width for histogram bars
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student says what each column, row, axis or bar stands for before calculating
  - The student uses every frequency, midpoint or class width the method needs
  - The student reaches a checked value that lies inside the spread of the data
---

# Statistics: averages, tables and charts

## When to use

Use when a problem asks to classify data, read or complete a table, find a mean, median, mode or range, estimate a
mean from grouped data, find pie chart angles, describe correlation or use a line of best fit, estimate quartiles from
cumulative frequency, or find frequency densities for a histogram.

Not for: probabilities of events (use mth-o-probability), or finding the equation of a straight line (use
mth-o-coordinate-geometry).

## What this skill does not do

- It does not compute standard deviation.
- It does not draw a line of best fit by calculation; the student places it by eye or the question gives it.
- It does not claim that correlation shows cause.

## Objectives

1. The student says what each column, row, axis or bar stands for before calculating.
2. The student uses every frequency, midpoint or class width the method needs.
3. The student reaches a checked value that lies inside the spread of the data.

## Prerequisite probe

- "Work out (3 + 5 + 10) ÷ 3." Expected: 6.
- "Four pens cost $2.40. What do ten pens cost?" Expected: $6.00.

If either fails, step back to the order of operations or to direct proportion, then return.

## Teaching sequence

1. Ask the student to say what the data, each column or each axis stands for. Done when every heading is explained.
2. Ask which measure or diagram the question wants. Done when the student names it and its method.
3. For tables, ask the student to add the frequencies and, where needed, the products f × x with midpoints. Done when both totals are on the board.
4. Ask the student to work out the measure; the stats_compute result is the reference value. Done when the student's value matches the checked value.
5. For pie charts and histograms, ask for each angle or frequency density; the math_evaluate result is the reference value. Done when the angles add to 360° or each density matches.
6. Ask for a sense check: an average lies between the smallest and largest values. Done when the student states the check.

## Hint ladder

1. Orient: "What does each number in the table count?"
2. Concept: name the method, such as "the mean is the total of all values divided by how many values there are".
3. First step: add a column for f × x and ask the student to fill the first row.
4. Worked step: show the two totals and ask the student for the division.
5. Full step: show the checked value; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.coded_numbers_quantitative`: treats shirt numbers as quantitative → "Does it make sense to find the mean of shirt numbers?"
- `mc.mth.o.table_total_ignored`: adds known entries to the total → "Should the missing entry be bigger or smaller than the total?"
- `mc.mth.o.median_not_ordered`: takes the middle of the list as written → "Is the list in order from smallest to largest?"
- `mc.mth.o.mode_as_frequency`: gives how often the mode occurs → "Is the answer one of the data values?"
- `mc.mth.o.frequency_mean_rows`: divides Σfx by the number of rows → "How many people were counted altogether?"
- `mc.mth.o.grouped_upper_bound`: uses the top of each class → "Where is a typical value in a class from 10 to 20?"
- `mc.mth.o.pie_percent_for_degrees`: uses the percentage as the angle → "Does a full pie chart go round 100 degrees or 360?"
- `mc.mth.o.correlation_causation`: says one quantity causes the other → "Could something else make both go up together?"
- `mc.mth.o.median_position_as_value`: gives n/2 as the median → "Is that a position on the axis of counts or a value of the data?"
- `mc.mth.o.histogram_height_as_frequency`: reads bar height as frequency → "What is the class width, and what is the area of the bar?"

## Confidence and escalation

- Two failures with a frequency table: switch representation and write out the list the table stands for.
- Three failures on the arithmetic: detour to the order of operations, then return.
- Data from a local survey the student cannot explain: save a local question for human help.

## Worked exchange

> Tutor: A table shows goals scored in 20 matches: 0 goals 4 times, 1 goal 6 times, 2 goals 7 times, 3 goals 3 times. Find the mean. What is the total frequency?
> Student: 4 + 6 + 7 + 3 = 20 matches.
> Tutor: Good. What is the total number of goals?
> Student: 0 × 4 + 1 × 6 + 2 × 7 + 3 × 3 = 29.
> Tutor: What do you divide by?
> Student: 20 matches, so 29 ÷ 20 = 1.45 goals.
> Tutor: Right (checked with the statistics tool), and 1.45 lies between 0 and 3.

## Verification checklist

- Every number shown comes from the question or from a stats_compute or math_evaluate check.
- The total frequency matches the number of data values.
- Pie chart angles add to 360°.
- Frequency density is frequency divided by class width.
- An average lies between the smallest and largest values, given to 3 significant figures if inexact.
