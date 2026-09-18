#!/bin/bash

# Manual Test Case Generator
# Interactive workflow for creating comprehensive test cases
#
# ИСПРАВЛЕНО относительно оригинала github/awesome-copilot:
#   1. eval "$var_name=..." заменён на printf -v (инъекция шелла при кавычках/бэктиках во вводе)
#   2. Переносы строк собирались как литеральный "\n" и попадали в markdown как текст,
#      а не как перевод строки — файл склеивался в одну строку
#   3. ((STEP_NUM++)) при set -e падает, когда значение 0 — заменено на арифметическое присваивание

set -e

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
MAGENTA='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${BLUE}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Manual Test Case Generator                 ║${NC}"
echo -e "${BLUE}╚══════════════════════════════════════════════════╝${NC}"
echo ""

# Безопасное присваивание: printf -v не интерпретирует содержимое ввода
prompt_input() {
    local prompt_text="$1"
    local var_name="$2"
    local required="$3"
    local input

    while true; do
        echo -e "${CYAN}${prompt_text}${NC}"
        read -r input

        if [ -n "$input" ]; then
            printf -v "$var_name" '%s' "$input"
            break
        elif [ "$required" != "true" ]; then
            printf -v "$var_name" '%s' ""
            break
        else
            echo -e "${RED}This field is required.${NC}"
        fi
    done
}

echo -e "${MAGENTA}━━━ Step 1: Test Case Basics ━━━${NC}"
echo ""

prompt_input "Test Case ID (e.g., TC-LOGIN-001):" TC_ID true
prompt_input "Test Case Title:" TC_TITLE true

echo ""
echo "Priority:"
echo "1) P0 - Critical (blocks release)"
echo "2) P1 - High (important features)"
echo "3) P2 - Medium (nice to have)"
echo "4) P3 - Low (minor issues)"
echo ""

prompt_input "Select priority (1-4):" PRIORITY_NUM true

case $PRIORITY_NUM in
    1) PRIORITY="P0 (Critical)" ;;
    2) PRIORITY="P1 (High)" ;;
    3) PRIORITY="P2 (Medium)" ;;
    4) PRIORITY="P3 (Low)" ;;
    *) PRIORITY="P2 (Medium)" ;;
esac

echo ""
echo "Test Type:"
echo "1) Functional"
echo "2) UI/Visual"
echo "3) Integration"
echo "4) Regression"
echo "5) Performance"
echo "6) Security"
echo ""

prompt_input "Select test type (1-6):" TYPE_NUM true

case $TYPE_NUM in
    1) TEST_TYPE="Functional" ;;
    2) TEST_TYPE="UI/Visual" ;;
    3) TEST_TYPE="Integration" ;;
    4) TEST_TYPE="Regression" ;;
    5) TEST_TYPE="Performance" ;;
    6) TEST_TYPE="Security" ;;
    *) TEST_TYPE="Functional" ;;
esac

prompt_input "Estimated test time (minutes):" EST_TIME false

echo ""
echo -e "${MAGENTA}━━━ Step 2: Test Objective ━━━${NC}"
echo ""

prompt_input "What are you testing? (objective):" OBJECTIVE true
prompt_input "Why is this test important?" WHY_IMPORTANT false

echo ""
echo -e "${MAGENTA}━━━ Step 3: Preconditions ━━━${NC}"
echo ""

echo "Enter preconditions (one per line, press Enter twice when done):"
PRECONDITIONS=""
while true; do
    read -r line
    if [ -z "$line" ]; then
        break
    fi
    # Настоящий перевод строки через $'\n', а не литеральные два символа
    PRECONDITIONS="${PRECONDITIONS}- ${line}"$'\n'
done

echo ""
echo -e "${MAGENTA}━━━ Step 4: Test Steps ━━━${NC}"
echo ""

echo "Enter test steps (format: action | expected result)"
echo "Type 'done' when finished"
echo ""

TEST_STEPS=""
STEP_NUM=1

while true; do
    echo -e "${YELLOW}Step $STEP_NUM:${NC}"
    prompt_input "Action:" ACTION false

    if [ "$ACTION" = "done" ] || [ -z "$ACTION" ]; then
        break
    fi

    prompt_input "Expected result:" EXPECTED true

    TEST_STEPS="${TEST_STEPS}${STEP_NUM}. ${ACTION}"$'\n'"   **Expected:** ${EXPECTED}"$'\n\n'
    STEP_NUM=$((STEP_NUM + 1))
done

echo ""
echo -e "${MAGENTA}━━━ Step 5: Test Data ━━━${NC}"
echo ""

prompt_input "Test data required (e.g., user credentials, sample data):" TEST_DATA false

echo ""
if [ "$TEST_TYPE" = "UI/Visual" ]; then
    echo -e "${MAGENTA}━━━ Step 6: Figma Design Validation ━━━${NC}"
    echo ""

    prompt_input "Figma design URL (if applicable):" FIGMA_URL false
    prompt_input "Visual elements to validate:" VISUAL_CHECKS false
fi

echo ""
echo -e "${MAGENTA}━━━ Step 7: Additional Info ━━━${NC}"
echo ""

prompt_input "Edge cases or variations to consider:" EDGE_CASES false
prompt_input "Related test cases (IDs):" RELATED_TCS false
prompt_input "Notes or comments:" NOTES false

FILENAME="${TC_ID}.md"
FILENAME="${FILENAME//[^a-zA-Z0-9_.-]/}"

OUTPUT_DIR="."
if [ -n "$1" ]; then
    OUTPUT_DIR="$1"
fi

OUTPUT_FILE="$OUTPUT_DIR/$FILENAME"

echo ""
echo -e "${BLUE}Generating test case...${NC}"
echo ""

cat > "$OUTPUT_FILE" << EOF
# ${TC_ID}: ${TC_TITLE}

**Priority:** ${PRIORITY}
**Type:** ${TEST_TYPE}
**Status:** Not Run
**Estimated Time:** ${EST_TIME:-TBD} minutes
**Created:** $(date +%Y-%m-%d)

---

## Objective

${OBJECTIVE}

${WHY_IMPORTANT:+**Why this matters:** ${WHY_IMPORTANT}}

---

## Preconditions

${PRECONDITIONS}
---

## Test Steps

${TEST_STEPS}
---

## Test Data

${TEST_DATA:-No specific test data required}

---

EOF

if [ "$TEST_TYPE" = "UI/Visual" ] && [ -n "$FIGMA_URL" ]; then
    cat >> "$OUTPUT_FILE" << EOF
## Visual Validation (Figma)

**Design Reference:** ${FIGMA_URL}

**Elements to validate:**
${VISUAL_CHECKS}

**Verification checklist:**
- [ ] Layout matches Figma design
- [ ] Spacing (padding/margins) accurate
- [ ] Typography (font, size, weight, color) correct
- [ ] Colors match design system
- [ ] Component states (hover, active, disabled) implemented
- [ ] Responsive behavior as designed

---

EOF
fi

cat >> "$OUTPUT_FILE" << EOF
## Post-conditions

- [Describe system state after test execution]
- [Any cleanup required]

---

## Edge Cases & Variations

${EDGE_CASES:-Consider boundary values, null inputs, special characters, concurrent users}

---

## Related Test Cases

${RELATED_TCS:-None}

---

## Execution History

| Date | Tester | Build | Result | Notes |
|------|--------|-------|--------|-------|
| | | | Not Run | |

---

## Notes

${NOTES}

---

## Attachments

- [ ] Screenshots
- [ ] Screen recordings
- [ ] Console logs
- [ ] Network traces

EOF

echo -e "${GREEN}✅ Test case generated successfully!${NC}"
echo ""
echo -e "File location: ${BLUE}$OUTPUT_FILE${NC}"
echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Review test case for completeness"
echo "2. Add to test suite"
echo "3. Execute test and update results"
if [ "$TEST_TYPE" = "UI/Visual" ] && [ -n "$FIGMA_URL" ]; then
    echo "4. Validate against Figma design using MCP"
fi
echo ""
echo -e "${CYAN}Tip: Create multiple test cases for comprehensive coverage${NC}"
echo ""
