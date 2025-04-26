# cuny-scheduler-checker

## Overview

This repository provides a tool to automatically monitor CUNYfirst for open seats in specified class sections using GitHub Actions. When an open seat is detected in a course you're tracking, it sends a notification to a configured Discord webhook.

## Features

*   Periodically checks CUNYfirst for class availability via GitHub Actions.
*   Monitors user-specified courses defined in GitHub secrets.
*   Sends Discord notifications when a tracked class section opens.
*   Includes a GitHub Actions workflow for automated, scheduled checks every 10 minutes.

## Automating with GitHub Actions

This repository uses GitHub Actions to automatically check for open classes every 10 minutes.

To use this automation:

1.  **Fork this Repository:** Create your own copy of this repository by clicking the "Fork" button at the top right of the GitHub page.
2.  **Add Required Secrets:** In your forked repository, go to `Settings` > `Secrets and variables` > `Actions`. You need to securely store the following information as repository secrets so the workflow can use them:
    *   `CUNY_USERNAME`: Your CUNYfirst username (without the @cuny.edu).
    *   `CUNY_PASSWORD`: Your CUNYfirst password.
    *   `DISCORD_WEBHOOK_URL`: The URL for your Discord webhook.
    *   `COURSE_NAMES`: Comma-separated list of course subjects/catalogs (e.g., `"CSCI-101,MATH-200"`).
    *   `COURSE_CODES`: Comma-separated list of corresponding course codes (e.g., `"12345,6789"`).
    *   `DISCORD_USER_ID`: (Optional) Your Discord user ID if you want to be pinged.

    > **⚠️ Warning:** Your CUNYfirst credentials (`CUNY_USERNAME` and `CUNY_PASSWORD`) are sensitive. Ensure they are stored *only* as GitHub secrets in your *private* fork or a repository you trust. Do not commit them directly to your code.

    **Finding Discord Information:**
    *   **Webhook URL (`DISCORD_WEBHOOK_URL`):**
        1.  In your Discord server, go to `Server Settings` > `Integrations`.
        2.  Click `Webhooks` > `New Webhook`.
        3.  Give it a name (e.g., "CUNY Notifier"), choose the channel it should post to.
        4.  Click `Copy Webhook URL`.
    *   **User ID (`DISCORD_USER_ID`):**
        1.  In Discord, go to `User Settings` > `Advanced`.
        2.  Enable `Developer Mode`.
        3.  Close Settings. Right-click on your username in the user list or a chat message.
        4.  Click `Copy User ID`.

3.  **Enable the Workflow:** Go to the `Actions` tab in your forked repository. Find the "Check CUNY Classes" workflow and make sure it's enabled. If it hasn't run before or you want to test it immediately, you might need to trigger it manually: click the `Run workflow` dropdown on the right, then click the green `Run workflow` button.

Once set up and enabled, the workflow will run automatically every 10 minutes to check for your desired classes.

> **Note:** While the workflow is scheduled to run every 10 minutes, GitHub Actions scheduling can sometimes vary. The actual interval between runs might occasionally be longer depending on GitHub's infrastructure load.
