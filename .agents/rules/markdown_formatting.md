# Markdown & Formula Formatting Rules

## 1. No LaTeX Math Syntax
- DO NOT use LaTeX syntax or math delimiters (`$...$` or `$$...$$`), such as `\text{}`, `\frac{}{}`, `\max()`, `\Big\lceil`, `\mathbf{}`, `\begin{cases}`.
- The chat markdown parser does not render LaTeX math, causing ugly raw code to display.

## 2. Standard Plain-text & Code Block Formulas
- Always format formulas using clean code blocks (` ```text `) or inline code (` `formula` `) with standard Unicode symbols (`×`, `÷`, `≥`, `≤`, `≈`, `+`, `-`).
- Example (Block):
  ```text
  Số lượng cần nhập = max(0, (Forecast_14D + Safety_Stock) - On_Hand)
  ```
- Example (Inline):
  `Daily Velocity = Forecast_14D / 14`
