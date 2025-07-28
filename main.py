from src.config import m


if __name__ == "__main__":
    m.add(
        [{"role": "user", "content": "the name of Laura's dog is Arnoph"}],
        user_id="test",
    )

    # Add user_id to the search call
    search_results = m.search("What is the name of Laura's dog?", user_id="test")
    print("Connection working!" if search_results else "Failed")

    # Optional: Print the search results to see what was found
    if search_results:
        print("Search results:", search_results)
