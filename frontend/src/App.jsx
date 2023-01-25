import { useState } from 'react'
import './App.css'

function App() {
  const [count, setCount] = useState(0)

  return (
    <>
    <div className="dark:bg-gray-800 min-h-screen">
            <nav className="mb-4 bg-white dark:bg-gray-900 border-gray-200 rounded">
                <div className="container flex flex-wrap items-center justify-between mx-auto">
                    <a href="{% url 'index' %}" className="flex items-center">
                        <span className="text-4xl">⌚</span>
                        <span className="self-center text-xl font-semibold whitespace-nowrap text-white">Timetracker</span>
                    </a>
                    <div className="w-full md:block md:w-auto">
                        <ul
                            className="flex flex-col md:flex-row p-4 mt-4 dark:text-white">
                            <li><a className="block py-2 pl-3 pr-4 hover:underline" href="{% url 'add_game' %}">New Game</a></li>
                            <li><a className="block py-2 pl-3 pr-4 hover:underline" href="{% url 'add_platform' %}">New Platform</a></li>
                            {/* {% if game_available and platform_available %} */}
                                <li><a className="block py-2 pl-3 pr-4 hover:underline" href="{% url 'add_purchase' %}">New Purchase</a></li>
                            {/* {% endif %} */}
                            {/* {% if purchase_available %} */}
                                <li><a className="block py-2 pl-3 pr-4 hover:underline" href="{% url 'add_session' %}">New Session</a></li>
                            {/* {% endif %} */}
                            {/* {% if session_count > 0 %} */}
                                <li><a className="block py-2 pl-3 pr-4 hover:underline" href="{% url 'list_sessions' %}">All Sessions</a></li>
                            {/* {% endif %} */}
                        </ul>
                    </div>
                </div>
            </nav>
            {/* {% block content %}No content here.{% endblock content %} */}
        </div>
        {/* {% load version %} */}
        {/* <span className="fixed left-2 bottom-2 text-xs text-slate-300 dark:text-slate-600">{% version %} ({% version_date %})</span> */}
        </>
  )
}

export default App
