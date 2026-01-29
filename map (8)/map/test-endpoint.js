// Test file to verify server endpoint
fetch("/api/deepgram-config")
  .then((res) => res.json())
  .then((data) => console.log("Server response:", data))
  .catch((err) => console.error("Server error:", err));
