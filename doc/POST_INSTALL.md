One more step: the dashboard needs a GitHub token before it can check anything.

1. Create a **fine-grained personal access token** at https://github.com/settings/personal-access-tokens/new
   - Repository access: **All repositories** (for organisations, choose the organisation as the resource owner, or make one token per organisation).
   - Repository permissions, all **Read-only**: Metadata, Contents, Issues, Pull requests, Actions, Dependabot alerts.
   - Give it an expiry date and put a reminder in your calendar. When it expires, the dashboard shows a red banner and sends an alert.
2. In YunoHost, open **Apps > __APP__ > Config panel**, paste the token in **GitHub token**, and save.
3. Press **Run the check now**, then open https://__DOMAIN____PATH__

The check then runs every day at the time set in the config panel.
