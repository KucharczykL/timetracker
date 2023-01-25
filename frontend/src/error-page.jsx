import { useRouteError } from "react-router-dom";

export default function ErrorPage() {
    const error = useRouteError()
    console.error(error)

    return (
        <div className="container text-center">
            <h1 className="text-3xl">Oops!</h1>
            <p>Sorry, an unexpected error has occurred.</p>
            <p>
                <i>{error.statusText || error.message}</i>
            </p>
        </div>
    )
}