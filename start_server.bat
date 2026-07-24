@echo off
cd /d "c:\geminiprojects\article generator\article-generator"

:: Uncomment and set your Gemini API Key below if you don't want to type it on mobile:
:: set GEMINI_API_KEY=YOUR_GEMINI_API_KEY_HERE

echo ===================================================
echo   Article Generator Server Starting...
echo ===================================================
echo.
echo  [Option 1] If your phone is on the SAME WI-FI as your PC:
echo  Open this link on your phone:
echo  http://192.168.0.110:8000/
echo.
echo ===================================================
start "ArticleGen Server" python -m articlegen web

echo Starting Public Tunnel via localtunnel...
start "ArticleGen Public Tunnel" npx localtunnel --port 8000
