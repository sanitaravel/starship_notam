# Bugfix Requirements Document

## Introduction

The FCC ELS bot posts the same application to Telegram twice: first an incomplete message that is missing the "Цель эксплуатации" (purpose of operation) and "Обоснование" (Explanation) fields, then, roughly one run later, a duplicate complete message that includes those fields.

This happens because an application can be persisted and posted while its detail is still empty (`detail_json = '{}'`). When a later run finally populates the detail, the `payload_hash` changes, `save_fcc_els_application` sees "changes detected", resets `telegram_posted` to 0, and the orchestrator posts the application a second time as if it were new.

Observed instance: file number `1514-EX-ST-2026` (application_seq 153213) was posted at 20:02 with `detail_json = '{}'` (telegram_message_id 735,736), then posted again at 20:32 with fully populated detail (telegram_message_id 737,738). The `payload_hash` differed between the two runs (`661420887be7...` vs `54b776f44ba...`), which is what re-triggered the post.

The desired outcome is a single Telegram post per application that already contains the complete detail (purpose of operation and Explanation), and no duplicate incomplete-then-complete pair.

## Bug Analysis

### Current Behavior (Defect)

When an FCC ELS application first appears with an empty detail (`detail == {}` / `detail_json == '{}'`) and later appears with a populated detail, the bot posts it twice.

1.1 WHEN an FCC ELS application is scraped with an empty detail (`detail == {}`) THEN the system saves it and posts it to Telegram with a message that omits "Цель эксплуатации" and "Обоснование"
1.2 WHEN a previously posted application is re-scraped with a now-populated detail THEN the system detects a `payload_hash` change, resets `telegram_posted` to 0, and posts the application a second time (a duplicate) instead of updating the original message
1.3 WHEN the detail transitions from empty to populated THEN the system produces two distinct Telegram messages for the same `file_number` (first incomplete, then complete)

### Expected Behavior (Correct)

2.1 WHEN an FCC ELS application is scraped with an empty detail (`detail == {}`) and has never been posted THEN the system SHALL NOT post it yet, deferring the post until the detail is populated
2.2 WHEN an FCC ELS application later has a populated detail THEN the system SHALL post it exactly once, and that single message SHALL include "Цель эксплуатации" and "Обоснование"
2.3 WHEN the only change to an already-posted application is the detail transitioning from empty to populated THEN the system SHALL NOT emit a second, duplicate Telegram message for the same `file_number`

### Unchanged Behavior (Regression Prevention)

3.1 WHEN an FCC ELS application is scraped with a populated detail on its first appearance THEN the system SHALL CONTINUE TO save and post it exactly once with the complete message
3.2 WHEN an already-posted application is re-scraped with no meaningful change THEN the system SHALL CONTINUE TO skip the DB update and NOT re-post it
3.3 WHEN a genuinely new FCC ELS application (new `file_number`) with a populated detail appears THEN the system SHALL CONTINUE TO post it to Telegram
3.4 WHEN posting any application, THEN the system SHALL CONTINUE TO render all existing header fields (Заявитель, Номер дела, Позывной, Статус, Дата получения, Дата статуса) and the "Открыть заявку" link as it does today
3.5 WHEN other content types (NOTAMs, FAA activities, beach alerts, road alerts) are processed THEN the system SHALL CONTINUE TO be posted as they are today, unaffected by this fix

## Bug Condition

**Bug Condition Function** — identifies inputs that trigger the bug:

```pascal
FUNCTION isBugCondition(X)
  INPUT: X of type FccElsApplication (as scraped/saved over time)
  OUTPUT: boolean

  // The bug is triggered when an application is posted while its detail
  // is empty, so that a later run with a populated detail re-posts it.
  RETURN (X.detail is empty at time of first post)
         AND (X.detail becomes populated on a later scrape)
END FUNCTION
```

**Property Specification** — Fix Checking (desired behavior for buggy inputs):

```pascal
// Property: Fix Checking — single complete post
FOR ALL X WHERE isBugCondition(X) DO
  posts ← telegramPostsFor(F', X.file_number)
  ASSERT count(posts) = 1
     AND detailFieldsPresent(posts[0])   // "Цель эксплуатации" AND "Обоснование"
END FOR
```

**Preservation Goal** — Preservation Checking (non-buggy inputs unchanged):

```pascal
// Property: Preservation Checking
FOR ALL X WHERE NOT isBugCondition(X) DO
  ASSERT F(X) = F'(X)
END FOR
```

Where **F** is the current (unfixed) behavior and **F'** is the fixed behavior.
