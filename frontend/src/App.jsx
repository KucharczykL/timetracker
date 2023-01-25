import { useState } from "react";
import "./App.css";
import Nav from "./components/Nav";

function App() {
  const [count, setCount] = useState(0);

  return (
    <>
      <div className="dark:bg-gray-800 min-h-screen">
        <Nav />
        {/* {% block content %}No content here.{% endblock content %} */}
      </div>
      {/* {% load version %} */}
      {/* <span className="fixed left-2 bottom-2 text-xs text-slate-300 dark:text-slate-600">{% version %} ({% version_date %})</span> */}
    </>
  );
}

export default App;
