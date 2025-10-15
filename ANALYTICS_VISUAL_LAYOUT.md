# Analytics Dashboard - Visual Layout

## 📐 Page Structure

```
┌─────────────────────────────────────────────────────────────────┐
│  Analytics for [Chatbot Name]            [← Back to Chatbot]   │
└─────────────────────────────────────────────────────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│  💬 TOTAL        │  │  ✅ RESOLVED     │  │  📊 RESOLUTION   │  │  📝 AVG MSG      │
│  INTERACTIONS    │  │     COUNT        │  │     RATE         │  │    LENGTH        │
│                  │  │                  │  │                  │  │                  │
│      150         │  │       120        │  │      80%         │  │      45          │
│   (Blue Card)    │  │  (Green Card)    │  │   (Info Card)    │  │  (Yellow Card)   │
└──────────────────┘  └──────────────────┘  └──────────────────┘  └──────────────────┘

┌─────────────────────────────────────────────────────┐  ┌─────────────────────┐
│  📈 CONVERSATION TRENDS (Last 30 Days)              │  │  🥧 STATUS          │
│  ┌───────────────────────────────────────────────┐ │  │    BREAKDOWN        │
│  │                                               │ │  │  ┌───────────────┐ │
│  │       ╱╲    ╱╲                               │ │  │  │               │ │
│  │      ╱  ╲  ╱  ╲    ╱╲                       │ │  │  │   Doughnut    │ │
│  │     ╱    ╲╱    ╲  ╱  ╲                      │ │  │  │     Chart     │ │
│  │    ╱            ╲╱    ╲                     │ │  │  │               │ │
│  │   ╱                    ╲___                 │ │  │  └───────────────┘ │
│  │  ╱                         ╲___             │ │  │  ┌─────────────┐   │
│  │ ────────────────────────────────────────── │ │  │  │ Resolved: 80 │   │
│  └───────────────────────────────────────────────┘ │  │  Active: 15  │   │
│                                                      │  │  Pending: 5  │   │
│  Line Chart with Gradient Fill                      │  └─────────────┘   │
└─────────────────────────────────────────────────────┘  └─────────────────────┘

┌─────────────────────────────────────────────┐  ┌───────────────────────────────┐
│  ❓ TOP QUESTIONS ASKED                     │  │  🏷️ AI-POWERED KEYWORDS       │
│  ┌─────────────────────────────────────┐   │  │  ┌─────────────────────────┐ │
│  │ 1. What are your pricing plans?     │   │  │  │                         │ │
│  │    ████████████████░░░░  30%  (45)  │   │  │  │  pricing  plans         │ │
│  ├─────────────────────────────────────┤   │  │  │      chatbot            │ │
│  │ 2. How do I create a chatbot?       │   │  │  │  integrate  website     │ │
│  │    ██████████░░░░░░░░░░  20%  (30)  │   │  │  │     upload              │ │
│  ├─────────────────────────────────────┤   │  │  │  documents  train       │ │
│  │ 3. Can I integrate with website?    │   │  │  │      features           │ │
│  │    ██████░░░░░░░░░░░░░░  15%  (22)  │   │  │  │  support  custom        │ │
│  ├─────────────────────────────────────┤   │  │  │                         │ │
│  │ 4. How do I upload documents?       │   │  │  └─────────────────────────┘ │
│  │    ████░░░░░░░░░░░░░░░░  10%  (15)  │   │  │                              │
│  ├─────────────────────────────────────┤   │  │  Visual Word Cloud           │
│  │ 5. How do I train my chatbot?       │   │  │  (Size = Relevance Score)    │
│  │    ████░░░░░░░░░░░░░░░░  10%  (15)  │   │  └──────────────────────────────┘
│  └─────────────────────────────────────┘   │
│                                             │
│  List with Progress Bars                    │
└─────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  ⏰ ACTIVITY PATTERNS                                                       │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐            │
│  │   ☀️ BUSIEST    │  │  📅 BUSIEST     │  │  📊 TOTAL       │            │
│  │      HOUR       │  │      DAY        │  │    PATTERNS     │            │
│  │                 │  │                 │  │                 │            │
│  │    2:00 PM      │  │    Monday       │  │       24        │            │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘            │
│                                                                             │
│  ┌───────────────────────────────────────────────────────────────────────┐ │
│  │  Hourly Distribution Chart                                           │ │
│  │  ║                                                                   │ │
│  │  ║     █                                                             │ │
│  │  ║     █     █                                                       │ │
│  │  ║     █     █     █                                                 │ │
│  │  ║     █     █     █     █                                           │ │
│  │  ║ █   █ █   █ █   █ █   █ █   █ █                                   │ │
│  │  ╚═══════════════════════════════════════════════════════════════════ │ │
│  │    12AM 3AM 6AM 9AM 12PM 3PM 6PM 9PM                                │ │
│  └───────────────────────────────────────────────────────────────────────┘ │
│                                                                             │
│  Bar Chart showing 24-hour conversation volume                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 🎨 Color Scheme

### Metric Cards
```
┌─────────────────┐
│ 🔵 PRIMARY      │  ← Total Interactions
│   (Blue)        │
└─────────────────┘

┌─────────────────┐
│ 🟢 SUCCESS      │  ← Resolved Count
│   (Green)       │
└─────────────────┘

┌─────────────────┐
│ 🔷 INFO         │  ← Resolution Rate
│   (Cyan)        │
└─────────────────┘

┌─────────────────┐
│ 🟡 WARNING      │  ← Avg Message Length
│   (Yellow)      │
└─────────────────┘
```

### Charts
```
Conversation Trends:
- Line: Blue (#36A2EB)
- Fill: Blue with transparency
- Grid: Light gray

Status Breakdown:
- Resolved: Green (#28A745)
- Active: Blue (#0D6EFD)
- Pending: Yellow (#FFC107)

Hourly Activity:
- Bars: Red (#DC3545)
- Border: Darker red
```

## 📱 Responsive Breakpoints

### Desktop (> 992px)
```
┌────────────────────────────────────────┐
│  [Card]  [Card]  [Card]  [Card]        │
│                                        │
│  [Large Chart]         [Small Chart]  │
│                                        │
│  [Questions]           [Keywords]     │
│                                        │
│  [Time Analytics - Full Width]        │
└────────────────────────────────────────┘
```

### Tablet (768px - 991px)
```
┌─────────────────────────────┐
│  [Card]  [Card]             │
│  [Card]  [Card]             │
│                             │
│  [Chart - Full Width]       │
│                             │
│  [Chart - Full Width]       │
│                             │
│  [Questions - Full Width]   │
│                             │
│  [Keywords - Full Width]    │
│                             │
│  [Time - Full Width]        │
└─────────────────────────────┘
```

### Mobile (< 768px)
```
┌──────────────────┐
│    [Card]        │
│    [Card]        │
│    [Card]        │
│    [Card]        │
│                  │
│  [Chart - Full]  │
│                  │
│  [Chart - Full]  │
│                  │
│  [Questions]     │
│                  │
│  [Keywords]      │
│                  │
│  [Time]          │
└──────────────────┘
```

## 🎭 Animations

### On Page Load
```
Cards:      Fade in + Slide up (staggered)
Charts:     Animate from 0 to actual values
Progress:   Fill from left to right
Keywords:   Fade in with scale
```

### On Hover
```
Cards:      Lift up + Shadow increase
Keywords:   Scale up + Shadow
Questions:  Background highlight
Charts:     Tooltip appears
```

## 🔄 Data Flow Visualization

```
                         User Opens Analytics
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Flask Route           │
                    │  /chatbot/{id}/        │
                    │  analytics             │
                    └────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Fetch Conversations   │
                    │  from Database         │
                    └────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  AnalyticsService      │
                    │  .get_conversation_    │
                    │  analytics()           │
                    └────────────────────────┘
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
        ┌──────────────────┐      ┌──────────────────┐
        │  Calculate       │      │  Extract         │
        │  Metrics         │      │  Keywords (AI)   │
        └──────────────────┘      └──────────────────┘
                    │                         │
                    └────────────┬────────────┘
                                 ▼
                    ┌────────────────────────┐
                    │  Render Template       │
                    │  analytics.html        │
                    └────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  Chart.js Renders      │
                    │  Visual Charts         │
                    └────────────────────────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │  User Views            │
                    │  Analytics Dashboard   │
                    └────────────────────────┘
```

## 💡 Interactive Elements

### Clickable Areas
```
┌─────────────────┐
│  Back Button    │  → Returns to chatbot details
└─────────────────┘

┌─────────────────┐
│  Keyword Tag    │  → Hover for scale effect
└─────────────────┘

┌─────────────────┐
│  Chart Points   │  → Hover for tooltip
└─────────────────┘
```

## 🎪 Empty State

When no conversations exist:

```
┌─────────────────────────────────────────┐
│                                         │
│           ℹ️ Information                │
│                                         │
│  No conversations yet!                  │
│                                         │
│  Analytics will appear once users       │
│  start interacting with your chatbot.   │
│                                         │
└─────────────────────────────────────────┘
```

## 📊 Chart Details

### Conversation Trends (Line Chart)
- **Type**: Line with gradient fill
- **Data Points**: Last 30 days
- **X-Axis**: Dates (e.g., "Oct 01", "Oct 02")
- **Y-Axis**: Number of conversations
- **Interactions**: Hover for exact values

### Status Breakdown (Doughnut Chart)
- **Type**: Doughnut (hollow pie)
- **Segments**: Resolved (Green), Active (Blue), Pending (Yellow)
- **Center**: Empty space
- **Legend**: Below chart with counts

### Hourly Activity (Bar Chart)
- **Type**: Vertical bars
- **Bars**: 24 (one per hour)
- **X-Axis**: Time labels (12 AM, 1 AM, etc.)
- **Y-Axis**: Conversation count
- **Highlight**: Busiest hour has different color

---

This visual layout provides a comprehensive, user-friendly analytics experience that helps users understand their chatbot's performance at a glance.

