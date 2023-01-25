export default function SessionList() {
  const data = [
    {
        "url": "http://localhost:8000/api/sessions/25/",
        "timestamp_start": "2020-01-01T00:00:00+01:00",
        "timestamp_end": null,
        "duration_manual": "12:00:00",
        "duration_calculated": "00:00:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/26/",
        "timestamp_start": "2022-12-31T15:25:00+01:00",
        "timestamp_end": "2022-12-31T17:25:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "02:00:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/2/"
    },
    {
        "url": "http://localhost:8000/api/sessions/27/",
        "timestamp_start": "2023-01-01T23:00:00+01:00",
        "timestamp_end": "2023-01-02T00:28:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "01:28:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/28/",
        "timestamp_start": "2023-01-02T22:08:00+01:00",
        "timestamp_end": "2023-01-03T01:08:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "03:00:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/29/",
        "timestamp_start": "2023-01-03T22:36:00+01:00",
        "timestamp_end": "2023-01-04T00:12:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "01:36:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/30/",
        "timestamp_start": "2023-01-04T20:35:00+01:00",
        "timestamp_end": "2023-01-04T22:36:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "02:01:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/31/",
        "timestamp_start": "2023-01-06T18:48:00+01:00",
        "timestamp_end": "2023-01-06T23:39:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "04:51:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/32/",
        "timestamp_start": "2023-01-07T23:49:00+01:00",
        "timestamp_end": "2023-01-08T01:43:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "01:54:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/33/",
        "timestamp_start": "2023-01-08T16:21:00+01:00",
        "timestamp_end": "2023-01-08T18:27:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "02:06:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/34/",
        "timestamp_start": "2023-01-08T19:04:00+01:00",
        "timestamp_end": "2023-01-08T22:03:00+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "02:59:00",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/35/",
        "timestamp_start": "2023-01-09T19:35:48+01:00",
        "timestamp_end": "2023-01-09T22:13:20.519058+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "02:37:32.519058",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/3/"
    },
    {
        "url": "http://localhost:8000/api/sessions/36/",
        "timestamp_start": "2023-01-10T15:50:12+01:00",
        "timestamp_end": "2023-01-10T17:03:45.424429+01:00",
        "duration_manual": "00:00:00",
        "duration_calculated": "01:13:33.424429",
        "note": "",
        "purchase": "http://localhost:8000/api/purchases/4/"
    }
  ]
  const header = ["url", "timestamp_start", "timestamp_end", "duration_manual", "duration_calculated", "note", "purchase"]
  // const header = ["Name", "Platform", "Start", "End", "Duration", "Manage"]
  return (
        <>
          <div id="session-table" className="gap-4 shadow rounded-xl max-w-screen-lg mx-auto dark:bg-slate-700 p-2 justify-center">
              {header.map(column => {
                <div className="dark:border-white dark:text-slate-300 text-lg">{column}</div>
              })}
          {data.map(session => {
              <>
                <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.url }
                </a>
                <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.timestamp_start }
                </a>
              </div>
              <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.timestamp_end }
                </a>
              </div>
              <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.duration_manual }
                </a>
              </div>
              <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.duration_calculated }
                </a>
              </div>
              <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.note }
                </a>
              </div>
              <div className="dark:text-white overflow-hidden text-ellipsis whitespace-nowrap">
                <a className="hover:underline" href="">
                  { session.purchase }
                </a>
              </div>
              </div>
              </>
          })}
          </div>
        </>
  )
}