import { useEffect } from "react";

function App() {
  useEffect(() => {
    async function checkBackend() {
      try {
        const response = await fetch("http://127.0.0.1:8765/health");
        const data = await response.json();

        console.log("Backend Response:", data);
      } catch (error) {
        console.error("Failed to connect to backend:", error);
      }
    }

    checkBackend();
  }, []);

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        height: "100vh",
        backgroundColor: "white",
      }}
    >
      <h1>MeetingMind</h1>
    </div>
  );
}

export default App;