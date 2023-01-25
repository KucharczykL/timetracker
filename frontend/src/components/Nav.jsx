import { Link } from 'react-router-dom';

function Nav() {
  return (
    <nav className="mb-4 bg-white dark:bg-gray-900 border-gray-200 rounded">
      <div className="container flex flex-wrap items-center justify-between mx-auto">
        <Link
          to="/"
          className="flex items-center"
        >
          <span className="text-4xl">⌚</span>
          <span className="self-center text-xl font-semibold whitespace-nowrap text-white">
            Timetracker
          </span>
        </Link>
        <div className="w-full md:block md:w-auto">
          <ul className="flex flex-col md:flex-row p-4 mt-4 dark:text-white">
            <li>
              <a
                className="block py-2 pl-3 pr-4 hover:underline"
                href="{% url 'add_game' %}"
              >
                New Game
              </a>
            </li>
            <li>
              <a
                className="block py-2 pl-3 pr-4 hover:underline"
                href="{% url 'add_platform' %}"
              >
                New Platform
              </a>
            </li>
            {/* {% if game_available and platform_available %} */}
            <li>
              <a
                className="block py-2 pl-3 pr-4 hover:underline"
                href="{% url 'add_purchase' %}"
              >
                New Purchase
              </a>
            </li>
            {/* {% endif %} */}
            {/* {% if purchase_available %} */}
            <li>
              <a
                className="block py-2 pl-3 pr-4 hover:underline"
                href="{% url 'add_session' %}"
              >
                New Session
              </a>
            </li>
            {/* {% endif %} */}
            {/* {% if session_count > 0 %} */}
            <li>
              <Link
                className="block py-2 pl-3 pr-4 hover:underline"
                to="/sessions"
              >
                All Sessions
              </Link>
            </li>
            {/* {% endif %} */}
          </ul>
        </div>
      </div>
    </nav>
  );
}

export default Nav;
