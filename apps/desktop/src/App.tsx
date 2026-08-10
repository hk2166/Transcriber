import { APP_NAME } from "./config";

function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="sidebar__header">
          <span className="app-mark" aria-hidden />
          <h1 className="app-name">{APP_NAME}</h1>
        </div>

        <button className="new-meeting">
          <span aria-hidden>＋</span> New meeting
        </button>

        <nav className="meeting-list">
          <p className="meeting-list__empty">No meetings yet</p>
        </nav>

        <div className="sidebar__footer">
          <span className="dot dot--ok" />
          Backend connected
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div className="topbar__title">
            <h2>New recording</h2>
            <p className="topbar__sub">Ready when you are</p>
          </div>
          <div className="elapsed">00:00</div>
        </header>

        <section className="stage">
          <div className="source-selector" role="group" aria-label="Audio source">
            <button className="segment">Mic</button>
            <button className="segment">System</button>
            <button className="segment segment--active">Both</button>
          </div>

          <button className="record-button" aria-label="Start recording">
            <span className="record-button__icon" />
          </button>

          <div className="meter" aria-hidden>
            <div className="meter__fill" />
          </div>

          <p className="stage__hint">Press record to start</p>
        </section>
      </main>
    </div>
  );
}

export default App;