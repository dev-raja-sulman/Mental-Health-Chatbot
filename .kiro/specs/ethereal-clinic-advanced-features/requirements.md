# Requirements Document

## Introduction

This document defines the requirements for adding ten advanced features to The Ethereal Clinic — a Flask-based mental health chatbot that uses BERT classification and a local Ollama LLaMA 3.2 model. The existing system supports user authentication (Patient IDs like EC-XXXXXX), a SQLite database, seven mental health labels (Anxiety, Bipolar, Depression, Normal, Personality Disorder, Stress, Suicidal), crisis detection, and an admin panel with session history and counselor reply.

The advanced features span four domains: patient-facing analytics and wellness tools, AI conversation quality improvements, admin clinical oversight, and security hardening.

---

## Glossary

- **System**: The Ethereal Clinic Flask application as a whole.
- **Mood_Analytics_Dashboard**: The patient-facing page displaying mood trends, session scores, and label history.
- **Session_Report_Generator**: The admin-side component that produces printable/PDF session summaries.
- **Conversation_Memory_Manager**: The backend component that assembles full session context for LLM prompts.
- **BERT_Classifier**: The existing BERT-based mental health label classification component.
- **Rate_Limiter**: The backend middleware that enforces per-user message frequency limits.
- **Password_Manager**: The backend component handling password change requests.
- **Session_Timeout_Manager**: The backend component that detects and expires inactive sessions.
- **Wellness_Tips_Engine**: The component that selects and serves label-specific coping tips.
- **Crisis_Log**: The dedicated admin view listing all sessions and messages flagged as Suicidal.
- **User_Profile_Page**: The patient-facing page showing personal stats, session count, and mood history.
- **Mood_Score**: A numeric value (0–100) derived from the BERT label for a given message or session, where higher values indicate better mental wellness.
- **Session**: A continuous conversation thread identified by a unique session_id stored in the browser's localStorage.
- **Confidence_Score**: The probability (0–100%) output by the BERT softmax layer for the predicted label.
- **Admin**: An authenticated administrator accessing the admin panel at /admin.
- **Patient**: An authenticated user with a Patient ID (EC-XXXXXX) accessing the chat interface.
- **Inactivity_Period**: A configurable duration (default 30 minutes) after which a session is considered expired.

---

## Requirements

### Requirement 1: Mood Analytics Dashboard

**User Story:** As a Patient, I want to see a visual dashboard of my mood trends over the past week, so that I can understand patterns in my mental health and track my progress.

#### Acceptance Criteria

1. WHEN a Patient navigates to `/dashboard`, THE Mood_Analytics_Dashboard SHALL display a bar chart showing the Mood_Score for each day of the past 7 days.
2. WHEN a Patient navigates to `/dashboard`, THE Mood_Analytics_Dashboard SHALL display the distribution of BERT labels across all of the Patient's sessions as a percentage breakdown.
3. WHEN a Patient navigates to `/dashboard`, THE Mood_Analytics_Dashboard SHALL display the Mood_Score for each individual session in a chronological list.
4. WHEN a Patient has no session history, THE Mood_Analytics_Dashboard SHALL display a placeholder message indicating no data is available yet.
5. THE System SHALL compute the Mood_Score for a session by mapping BERT labels to numeric values: Normal=100, Anxiety=55, Stress=50, Bipolar=45, Depression=35, Personality Disorder=30, Suicidal=5.
6. THE System SHALL compute the daily Mood_Score as the average of all session Mood_Scores recorded on that calendar day.
7. WHEN a Patient views the dashboard, THE Mood_Analytics_Dashboard SHALL only display data belonging to the authenticated Patient's user_id.

---

### Requirement 2: Session Reports (PDF/Printable)

**User Story:** As an Admin, I want to generate a printable summary report for any patient session, so that I can share clinical notes with counselors or include them in patient records.

#### Acceptance Criteria

1. WHEN an Admin clicks "Print Report" for a session in the admin panel, THE Session_Report_Generator SHALL produce a printable HTML page containing the session ID, patient name, patient ID, session start time, session end time, all messages with timestamps and BERT labels, and the final session Mood_Score.
2. THE Session_Report_Generator SHALL be accessible at `/admin/report/<session_id>` and SHALL require admin authentication.
3. WHEN a session contains a message with a Suicidal label, THE Session_Report_Generator SHALL include a clearly visible crisis flag in the report header.
4. WHEN an Admin requests a report for a session_id that does not exist, THE Session_Report_Generator SHALL return an HTTP 404 response with a descriptive error message.
5. THE Session_Report_Generator SHALL render the report in a print-optimised layout (no navigation sidebar, clean typography) so that the browser's native print function produces a usable document.

---

### Requirement 3: Conversation Memory (Full Session Context)

**User Story:** As a Patient, I want the AI counselor to remember everything I said earlier in our conversation, so that responses feel coherent and I don't have to repeat myself.

#### Acceptance Criteria

1. WHEN the LLM prompt is built for a Patient's message, THE Conversation_Memory_Manager SHALL include all prior messages from the current session, not just the last 8 turns.
2. WHEN the full session history exceeds 4000 tokens (estimated at 3 characters per token), THE Conversation_Memory_Manager SHALL truncate the oldest messages first while always preserving the system prompt and the 4 most recent turns.
3. THE Conversation_Memory_Manager SHALL include both user messages and assistant/counselor messages from the session history in the prompt.
4. WHEN a counselor has sent a manual reply in the session, THE Conversation_Memory_Manager SHALL include that reply in the context with a "Counselor:" speaker label.
5. THE System SHALL continue to bypass the LLM and return the hardcoded EMERGENCY_RESPONSE when the BERT_Classifier returns a Suicidal label, regardless of session history length.

---

### Requirement 4: Confidence Scores

**User Story:** As a Patient and as an Admin, I want to see how confident the AI is in its mental health classification, so that I can gauge the reliability of the detection.

#### Acceptance Criteria

1. WHEN the BERT_Classifier classifies a message, THE BERT_Classifier SHALL return both the predicted label and the Confidence_Score as a percentage rounded to one decimal place.
2. WHEN the `/chat` endpoint returns a response, THE System SHALL include the `confidence` field (0.0–100.0) in the JSON response alongside the existing `label` field.
3. WHEN a message bubble is rendered in the chat interface, THE System SHALL display the Confidence_Score next to the BERT label badge (e.g., "Anxiety · 87.3%").
4. WHEN an Admin views a session in the admin panel modal, THE System SHALL display the Confidence_Score alongside each user message's label badge.
5. THE System SHALL store the Confidence_Score in the `messages` table alongside the label so that historical confidence data is preserved.

---

### Requirement 5: Rate Limiting

**User Story:** As an Admin, I want the system to prevent message spam, so that the server is not overloaded and the AI model is not abused.

#### Acceptance Criteria

1. WHEN a Patient sends more than 20 messages within any 60-second window from the same user_id, THE Rate_Limiter SHALL reject subsequent requests with an HTTP 429 response and a JSON body containing `{"error": "Too many messages. Please wait before sending again."}`.
2. WHEN a non-authenticated user (guest) sends more than 10 messages within any 60-second window from the same IP address, THE Rate_Limiter SHALL reject subsequent requests with an HTTP 429 response.
3. WHEN the Rate_Limiter rejects a request, THE chat interface SHALL display an inline warning message to the Patient without clearing the input field.
4. THE Rate_Limiter SHALL reset the message count for a user_id or IP address after the 60-second window expires.
5. THE Rate_Limiter SHALL operate in-memory and SHALL NOT require an external service such as Redis.

---

### Requirement 6: Password Change

**User Story:** As a Patient, I want to change my password from within the application, so that I can maintain account security without contacting an administrator.

#### Acceptance Criteria

1. WHEN an authenticated Patient submits a password change form with the correct current password, a new password, and a matching confirmation, THE Password_Manager SHALL update the stored password hash and return a success response.
2. WHEN an authenticated Patient submits a password change form with an incorrect current password, THE Password_Manager SHALL return an HTTP 400 response with `{"error": "Current password is incorrect."}` and SHALL NOT update the stored password.
3. WHEN the new password is fewer than 4 characters, THE Password_Manager SHALL return an HTTP 400 response with `{"error": "New password must be at least 4 characters."}`.
4. WHEN the new password and confirmation do not match, THE Password_Manager SHALL return an HTTP 400 response with `{"error": "Passwords do not match."}`.
5. THE Password_Manager SHALL be accessible at `POST /change-password` and SHALL require an authenticated session (user_id present in Flask session).
6. WHEN a password change succeeds, THE System SHALL invalidate the current Flask session and redirect the Patient to the login page with a success message.

---

### Requirement 7: Session Timeout

**User Story:** As an Admin, I want inactive patient sessions to expire automatically, so that unattended browser sessions do not remain accessible.

#### Acceptance Criteria

1. WHILE a Patient's Flask session has been inactive for longer than the Inactivity_Period, THE Session_Timeout_Manager SHALL invalidate the Flask session on the next request and redirect the Patient to the login page.
2. WHEN an authenticated Patient makes any request to the System, THE Session_Timeout_Manager SHALL update the session's last-activity timestamp.
3. THE Session_Timeout_Manager SHALL use a default Inactivity_Period of 30 minutes, configurable via the `SESSION_TIMEOUT_MINUTES` environment variable.
4. WHEN a session expires due to inactivity, THE System SHALL display the message "Your session expired due to inactivity. Please log in again." on the login page.
5. THE Session_Timeout_Manager SHALL apply to patient sessions only and SHALL NOT affect the admin session.

---

### Requirement 8: Wellness Tips

**User Story:** As a Patient, I want to see coping tips relevant to my current detected mood, so that I receive actionable guidance alongside the AI conversation.

#### Acceptance Criteria

1. WHEN the BERT_Classifier returns a label for a Patient's message, THE Wellness_Tips_Engine SHALL select and display a coping tip specific to that label in the right-hand sidebar of the chat interface.
2. THE Wellness_Tips_Engine SHALL maintain at least 3 distinct coping tips for each of the 7 labels: Anxiety, Bipolar, Depression, Normal, Personality Disorder, Stress, and Suicidal.
3. WHEN the label is Suicidal, THE Wellness_Tips_Engine SHALL display crisis resource information (988 Lifeline, Crisis Text Line) instead of general coping tips.
4. WHEN the label changes between messages, THE Wellness_Tips_Engine SHALL update the displayed tip to match the new label.
5. WHEN no label has been detected yet in the session, THE Wellness_Tips_Engine SHALL display a default welcome tip encouraging the Patient to share how they are feeling.
6. THE Wellness_Tips_Engine SHALL rotate through available tips for a label so that the same tip is not shown on consecutive messages with the same label.

---

### Requirement 9: Crisis Log

**User Story:** As an Admin, I want a dedicated view of all crisis events, so that I can quickly identify and follow up with patients who have expressed suicidal ideation.

#### Acceptance Criteria

1. WHEN an Admin navigates to `/admin/crisis-log`, THE Crisis_Log SHALL display a chronological list of all messages where the BERT label is Suicidal, including the session ID, patient name, patient ID, message content, timestamp, and Confidence_Score.
2. THE Crisis_Log SHALL require admin authentication and SHALL return an HTTP 401 response for unauthenticated requests.
3. WHEN an Admin clicks on a crisis entry, THE Crisis_Log SHALL open the full session history modal for that session (reusing the existing admin panel modal).
4. THE Crisis_Log SHALL display the total count of crisis events at the top of the page.
5. WHEN no crisis events exist, THE Crisis_Log SHALL display a message indicating no crisis events have been recorded.
6. THE Crisis_Log page SHALL be linked from the main admin panel navigation.
7. WHEN a new Suicidal message is saved, THE System SHALL increment a crisis event counter visible on the admin panel without requiring a page refresh (via the existing `/admin/stats` polling or a dedicated endpoint).

---

### Requirement 10: User Profile Page

**User Story:** As a Patient, I want to view my profile page showing my account details and mental health statistics, so that I can understand my usage and overall wellness history.

#### Acceptance Criteria

1. WHEN an authenticated Patient navigates to `/profile`, THE User_Profile_Page SHALL display the Patient's full name, username, Patient ID (EC-XXXXXX), account creation date, and last login date.
2. WHEN an authenticated Patient navigates to `/profile`, THE User_Profile_Page SHALL display the total number of sessions, total number of messages sent, and the most frequently detected BERT label across all sessions.
3. WHEN an authenticated Patient navigates to `/profile`, THE User_Profile_Page SHALL display the Patient's overall average Mood_Score computed across all sessions.
4. WHEN an authenticated Patient navigates to `/profile`, THE User_Profile_Page SHALL display a list of the Patient's 5 most recent sessions with their date, message count, and dominant label.
5. WHEN a Patient is not authenticated, THE System SHALL redirect requests to `/profile` to the login page.
6. THE User_Profile_Page SHALL include a link to the Password Change form (Requirement 6).
