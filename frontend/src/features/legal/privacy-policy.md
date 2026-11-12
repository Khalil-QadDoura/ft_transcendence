# Privacy Policy

Last updated: 2026-11-11

This policy explains what personal data WOZU Web collects, why, who can see it, how long we keep it and what you can do about it. We wrote it for this service, in plain words. If something is unclear, write to us: burhan.hajili@gmail.com.

## 1. Who we are

WOZU Web is a student project of five students of 42 Abu Dhabi: Burhan Hajili (bhajili), Khalil Kaddoura (kqaddour), Nader Khalil (nakhalil), Zayid Elkhair (zsid-ele) and Ahmad Radwan (aradwan). It is not a commercial service and there is no company behind it. The team is the operator of the service and is responsible for your data.

WOZU Web is a job platform. Candidates apply with a short video resume instead of a CV, chat with employers, and can play a mini-game called Turing Duel.

Contact for privacy requests and questions: burhan.hajili@gmail.com

The laws of the United Arab Emirates apply to this policy, including the Personal Data Protection Law (Federal Decree-Law No. 45 of 2021). We describe your rights in the style of the GDPR. We do not claim any GDPR certification.

## 2. Data we collect

### Account

- Your email address.
- Your password, stored only as a hash. We cannot read your password.
- Whether your email is verified.

### Profile

- First name, last name and position.
- Birth date. We use it only to check that you are at least 18.
- Short bio (optional).
- Avatar (optional).

### Video resume

- The video file you upload (MP4, up to 30 seconds).
- The result of the automatic check of the video: approved or rejected, and the reason when it is rejected.
- Whether the video is posted or not.

### Company and job data

If you create a company, we store its name, description, logo, country, city and district. For each job post we store the title, description, location, salary, schedule and urgency.

### Job applications

- The job you applied to, the video you applied with and your cover note (optional).
- The status of the application and its history (for example submitted, viewed, shortlisted, rejected, hired, withdrawn), with the date and an optional note from the employer.
- When you open a job as a signed-in user, we record the view. Employers only see the total number of views.

### Friends and chat

- Friend requests and your list of friends.
- Whether you are online.
- Your chat messages, with the time sent, the read state and the changes you make (edit or delete). Messages are visible to the people in that conversation.

### Turing Duel game

- The rooms you played in and the anonymous label you had ("Player 1", "Player 2" and so on).
- Your game messages and your votes (bot or human), and your score.
- Some players in a room may be bots. The game does not tell you which ones until the results.

### Technical data

- Technical logs of the service: the time of a request, which page or API was called, the result, a request ID and your IP address. IP addresses appear in the access logs of the front proxy. Logs are kept for up to 15 days.
- Metrics about how the service runs (for example number of requests and errors). They do not contain your content.
- Your IP address is also used by the front proxy to limit repeated requests (rate limiting), for example repeated sign-in attempts.

## 3. Why we use your data

- **To run your account.** Sign up, verify your email, sign in, reset your password. We also send you emails for these steps.
- **To provide the service you ask for.** Show your profile, post your video resume, send your application, let you chat, add friends, play the game.
- **To keep WOZU Web safe.** Check videos automatically, limit abuse, find and fix errors. See section 5 for the video check.
- **To keep the service working.** Logs and metrics help us find faults.

We rely on your consent, which you give when you create an account and accept the Terms of Service. Some processing is also needed to provide the service you asked for, and some to keep the service safe for everyone. You can withdraw your consent at any time by deleting your account (section 8).

After you delete your account we keep your data for 30 days because we have a legitimate need to establish or defend legal claims (UAE Personal Data Protection Law). We use it only to handle disputes, abuse reports and legal claims (section 6).

We do not use your data for advertising. We do not make decisions about you that have legal effects. The video check is only used to decide whether a video can be shown to others.

## 4. Who can see your data

- **The people running WOZU Web.** The team members with access to the servers can technically see stored data. We use this only to run, secure and fix the service.
- **Anyone, even if not signed in:** open job posts, with the company name.
- **Other signed-in users:** your profile (name, position, bio, avatar and whether you are online). Your email address and birth date are not shown to other users.
- **Other signed-in users:** your posted video resume. Videos in the video feed are shown with your name and position. This means your video is not limited to employers. Any signed-in user can see a video that is posted. You can unpost it at any time.
- **The employer of a job you applied to:** your application, cover note, the video you applied with and your profile.
- **People you chat with:** the messages you send them.
- **Players in your game room:** your anonymous label and your game messages. They do not see your name or profile. After the game, scores and which labels were bots are shown to the room.

Avatars and company logos have stable public links: anyone who has the link can download the image without signing in. The storage cannot be listed, so nobody can browse it to find other images. Video files are private. The service shows them only through short-lived links that expire: a link to watch a video works for 5 minutes by default and never for longer than one hour.

## 5. Third parties

### OpenAI

When you upload a video resume, an automatic check runs before the video can be posted. For this check we send to OpenAI:

- still images taken from your video (up to three frames, at 5, 15 and 25 seconds);
- the audio of your video, for transcription with OpenAI's Whisper model;
- the text of that transcript, for content moderation.

The check can show your face and your voice, and anything you say, to OpenAI. OpenAI processes this data on its own servers, which may be outside the United Arab Emirates, under its own terms and privacy policy (https://openai.com/policies/privacy-policy). We do not control what OpenAI does with the data after we send it. If you do not want this check, do not upload a video.

We do not send your profile, avatar, chat messages, game messages or company data to OpenAI.

### 42 intra sign-in

If sign-in with 42 is enabled, you can sign in with your 42 intra account. In that case 42 tells us the account details needed to create your account here, for example your email address and your 42 login. We do not receive your 42 password. Your use of 42 is covered by 42's own policy.

### No selling

We do not sell your data. We do not share it for advertising. Apart from the services above, we do not give your data to other companies.

## 6. Storage and retention

- Your account, profile, applications, chat and game data are stored in a PostgreSQL database.
- Videos, avatars and company logos are stored as files in MinIO, an object storage run by us.
- The service runs on servers operated by the team.
- We keep your account, profile, videos, applications and chats until you delete them or delete your account.
- When you delete your account, it happens in two stages. First, at once: your account is deactivated, you can no longer sign in, all your sessions end, your profile, videos and job posts are hidden from everyone, and your avatar and your company's logo are no longer publicly available (replacing an avatar or a logo deletes the old file at once). Second, after 30 days: an automatic job anonymises the account. Your email, name, birth date and bio are erased or replaced, and your avatar, logo and video files are deleted from storage. Applications and game records stay only in anonymised form. Chat messages you already sent stay visible to their recipients, shown as from "Deleted user".
- During those 30 days we keep your data only to handle disputes, abuse reports and legal claims, and only the team can access it. If a complaint or dispute about your account is open, we keep the data needed for it until it is resolved. Deleted data can then stay in a backup for up to 7 more days. Until you delete your account, you can also delete a single video yourself.
- Backups are kept for 7 days and then overwritten.
- Technical logs and metrics are kept for up to 15 days.

Connections between your browser and WOZU Web use HTTPS. Videos are opened through short-lived links. Passwords are stored as hashes. After repeated requests from one address, the service refuses further requests for a while.

## 7. Browser storage

WOZU Web stores in your browser only what it needs to work:

- your sign-in tokens, so that you stay signed in (they are removed when you sign out);
- your chosen language.

We do not use analytics, tracking or advertising cookies. We do not use third-party trackers.

## 8. Your rights

You can ask us to:

- **Access** your data: most of it is shown in the app, in your profile and your videos. For anything else, ask by email.
- **Correct** your data: change your profile in the app, or ask by email.
- **Delete** your data: in the app, open Settings and choose "Delete account". Your account is deactivated at once and anonymised after 30 days. You can also delete a single video, or a chat message you sent.
- **Give you a copy** of your data: ask by email. We send it to the address of your account.
- **Object** to the use of your data, or withdraw your consent: ask by email. If the processing is needed to run your account, we may have to close the account.

To use a right, write to burhan.hajili@gmail.com from the email address of your account, so we can check it is you. We answer as soon as we can. You may also complain to the data protection authority of the United Arab Emirates.

## 9. Age

WOZU Web is only for people aged 18 or older. The profile asks for your birth date and does not accept a younger age. If we learn that a person under 18 has an account, we close it and delete the data.

## 10. Changes to this policy

We may change this policy, for example when the service changes. The date at the top shows the last update. If you keep using WOZU Web after a change, the new text applies; if you disagree, you can delete your account.

## 11. Contact

Write to burhan.hajili@gmail.com for any question about this policy or your data.
