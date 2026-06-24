"""Static seed data for the search UI."""

# A starter list of strong coffee-culture cities worldwide. Users can edit the
# textarea freely; this is just a one-click "fill the world" convenience.
SEED_CITIES = [
    "London, UK", "Manchester, UK", "Edinburgh, UK", "Dublin, Ireland",
    "Paris, France", "Berlin, Germany", "Munich, Germany", "Amsterdam, Netherlands",
    "Brussels, Belgium", "Lisbon, Portugal", "Porto, Portugal", "Madrid, Spain",
    "Barcelona, Spain", "Rome, Italy", "Milan, Italy", "Vienna, Austria",
    "Zurich, Switzerland", "Copenhagen, Denmark", "Stockholm, Sweden", "Oslo, Norway",
    "Helsinki, Finland", "Prague, Czechia", "Warsaw, Poland", "Athens, Greece",
    "Istanbul, Turkey", "New York, USA", "Los Angeles, USA", "San Francisco, USA",
    "Seattle, USA", "Portland, USA", "Chicago, USA", "Austin, USA",
    "Miami, USA", "Boston, USA", "Toronto, Canada", "Vancouver, Canada",
    "Montreal, Canada", "Mexico City, Mexico", "Bogota, Colombia", "Sao Paulo, Brazil",
    "Buenos Aires, Argentina", "Cape Town, South Africa", "Johannesburg, South Africa",
    "Nairobi, Kenya", "Dubai, UAE", "Tel Aviv, Israel", "Sydney, Australia",
    "Melbourne, Australia", "Auckland, New Zealand", "Tokyo, Japan",
    "Seoul, South Korea", "Singapore", "Hong Kong", "Bangkok, Thailand",
    "Bali, Indonesia",
]

# Suggested base queries (the "in <city>" suffix is added per location).
QUERY_PRESETS = [
    "coffee shops",
    "specialty coffee shops",
    "cafes",
    "espresso bars",
    "coffee roasters",
]

# When "auto-expand" is on, each location is searched once per variant below.
# Google caps a single query at ~60 results, so running many overlapping
# phrasings (deduped by Place ID) is how we get well past 60 leads per city.
EXPANSION_QUERIES = [
    "specialty coffee shops",
    "cafes",
    "coffee roasters",
    "espresso bar",
    "coffee shop",
    "third wave coffee",
    "artisan coffee",
    "brunch cafe",
    "independent coffee shop",
    "coffee house",
]
