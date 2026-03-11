# ⚽ Compilation Creation Tool

A high-performance video compilation tool that leverages **WhoScored** event data to automate the highlight-reel process. Whether you're a scout, analyst, or content creator, this tool transforms raw match data into curated player clips.

---

## 🚀 Key Features

### ⏱️ Intelligent Video Syncing
Syncing match events with broadcast footage is often the most tedious part of editing. 
* **Automated Alignment:** Attempts to automatically sync match clock timestamps with video file time.
* **Manual Override:** While the tool simplifies the math for you, you can still manually calibrate offsets for frame-perfect cropping.

### 🔍 Precision Action Filtering
Don't wade through 90 minutes of footage. Drill down into exactly what you need:
* **Event Types:** Filter by specific match events including **Goals**, **Tackles**, **Aerial Duels**, and more.
* **Outcome Filtering:** Toggle between **Successful**, **Unsuccessful**, or both to analyze a player's full performance profile.

### 🎵 Custom Audio Profiles
Personalize the output for every player.
* Apply unique audio tracks to individual player compilations automatically during the render process.

### 🧵 Multi-Threaded Processing
Built for speed. 
* The tool utilizes **concurrent threading** to process multiple players simultaneously, significantly reducing the total time required for bulk exports.

---

## 📊 Data Source
This tool parses event data provided by **WhoScored**, ensuring industry-standard accuracy for all match timestamps and action categories.

---
