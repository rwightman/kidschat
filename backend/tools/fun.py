"""
Fun tools — jokes, facts, math evaluation, and weather.
These are lightweight tools that the local LLM can call
to enrich its responses.
"""

import logging
import random

import httpx

log = logging.getLogger("kidschat.tools.fun")


# ------------------------------------------------------------------
# Math
# ------------------------------------------------------------------
async def do_math(args: dict) -> dict:
    """
    Safely evaluate a math expression.

    Args: {"expression": "(15 * 3) + 7", "explain": true}
    Returns: {"text": "15 × 3 + 7 = 52"}
    """
    expression = args.get("expression", "")
    explain = args.get("explain", True)

    # Safety: only allow math characters
    allowed = set("0123456789+-*/().% ^sqrtabcdefghijklmnopqrstuvwxyz ")
    if not all(c in allowed for c in expression.lower()):
        return {"text": "I can only do math calculations — no funny business!"}

    try:
        # Use Python's eval with restricted builtins
        import math as mathlib

        safe_dict = {
            "__builtins__": {},
            "sqrt": mathlib.sqrt,
            "pi": mathlib.pi,
            "abs": abs,
            "round": round,
            "pow": pow,
            "min": min,
            "max": max,
        }
        result = eval(expression, safe_dict)

        if explain:
            text = f"Let me work that out:\n{expression} = **{result}**"
        else:
            text = f"{expression} = {result}"

        return {"text": text}

    except Exception as e:
        return {"text": f"Hmm, I couldn't calculate that: {expression}. Is it a valid math expression?"}


# ------------------------------------------------------------------
# Weather
# ------------------------------------------------------------------
async def get_weather(args: dict) -> dict:
    """
    Get current weather using the free Open-Meteo API (no key needed).

    Args: {"location": "Vancouver"}
    Returns: {"text": "It's 12°C and partly cloudy in Vancouver!"}
    """
    location = args.get("location", "")
    if not location:
        return {"text": "Which city do you want the weather for?"}

    try:
        async with httpx.AsyncClient() as client:
            # Step 1: Geocode the location
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en"},
                timeout=10.0,
            )
            geo_data = geo.json()

            if not geo_data.get("results"):
                return {"text": f"I couldn't find a place called '{location}'. Can you be more specific?"}

            place = geo_data["results"][0]
            lat, lon = place["latitude"], place["longitude"]
            name = place.get("name", location)
            country = place.get("country", "")

            # Step 2: Get current weather
            weather = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat,
                    "longitude": lon,
                    "current": "temperature_2m,weathercode,windspeed_10m",
                    "temperature_unit": "celsius",
                },
                timeout=10.0,
            )
            w = weather.json()["current"]

            temp = w["temperature_2m"]
            wind = w["windspeed_10m"]
            code = w["weathercode"]
            condition = _weather_code_to_text(code)
            emoji = _weather_code_to_emoji(code)

            text = (
                f"{emoji} In **{name}**, {country}, it's **{temp}°C** "
                f"and {condition}. Wind is blowing at {wind} km/h."
            )
            return {"text": text}

    except Exception as e:
        log.error(f"Weather error: {e}")
        return {"text": "I had trouble checking the weather. Try again in a moment!"}


def _weather_code_to_text(code: int) -> str:
    codes = {
        0: "clear skies", 1: "mostly clear", 2: "partly cloudy", 3: "overcast",
        45: "foggy", 48: "frosty fog", 51: "light drizzle", 53: "drizzle",
        55: "heavy drizzle", 61: "light rain", 63: "rain", 65: "heavy rain",
        71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
        80: "light showers", 81: "showers", 82: "heavy showers",
        95: "thunderstorms", 96: "thunderstorms with hail",
    }
    return codes.get(code, "interesting weather")


def _weather_code_to_emoji(code: int) -> str:
    if code == 0: return "☀️"
    if code <= 3: return "⛅"
    if code <= 48: return "🌫️"
    if code <= 55: return "🌦️"
    if code <= 65: return "🌧️"
    if code <= 77: return "❄️"
    if code <= 82: return "🌧️"
    return "⛈️"


# ------------------------------------------------------------------
# Jokes
# ------------------------------------------------------------------
JOKES = [
    {"q": "What do you call a bear with no teeth?", "a": "A gummy bear! 🐻"},
    {"q": "Why don't scientists trust atoms?", "a": "Because they make up everything! ⚛️"},
    {"q": "What do you call a sleeping dinosaur?", "a": "A dino-snore! 🦕💤"},
    {"q": "Why did the scarecrow win an award?", "a": "He was outstanding in his field! 🌾"},
    {"q": "What do you call a fish without eyes?", "a": "A fsh! 🐟"},
    {"q": "Why can't your nose be 12 inches long?", "a": "Because then it would be a foot! 👃"},
    {"q": "What do you call a dog that does magic?", "a": "A Labracadabrador! 🐕✨"},
    {"q": "Why did the banana go to the doctor?", "a": "Because it wasn't peeling well! 🍌"},
    {"q": "What do you call a lazy kangaroo?", "a": "A pouch potato! 🦘"},
    {"q": "What did the ocean say to the beach?", "a": "Nothing, it just waved! 🌊"},
    {"q": "Why do bees have sticky hair?", "a": "Because they use honeycombs! 🐝"},
    {"q": "What do you call a dinosaur that crashes their car?", "a": "Tyrannosaurus Wrecks! 🦖💥"},
]


async def tell_joke(args: dict) -> dict:
    """Tell a kid-friendly joke."""
    topic = args.get("topic", "").lower()

    # Try to find a topic-relevant joke
    if topic:
        matching = [j for j in JOKES if topic in j["q"].lower() or topic in j["a"].lower()]
        if matching:
            joke = random.choice(matching)
        else:
            joke = random.choice(JOKES)
    else:
        joke = random.choice(JOKES)

    return {"text": f"**{joke['q']}**\n\n{joke['a']}"}


# ------------------------------------------------------------------
# Fun Facts
# ------------------------------------------------------------------
FACTS = {
    "space": [
        "A day on Venus is longer than a year on Venus! It takes 243 Earth days to spin once, but only 225 days to orbit the Sun. 🪐",
        "There are more stars in the universe than grains of sand on Earth! ✨",
        "Neutron stars are so dense that a teaspoon of one would weigh about 6 billion tons! ⭐",
    ],
    "animals": [
        "Octopuses have three hearts and blue blood! 🐙",
        "A group of flamingos is called a 'flamboyance'! 🦩",
        "Sea otters hold hands while sleeping so they don't drift apart! 🦦",
        "Cows have best friends and get stressed when separated! 🐄",
    ],
    "science": [
        "Honey never spoils — archaeologists found 3,000-year-old honey in Egyptian tombs that was still edible! 🍯",
        "Bananas are slightly radioactive because they contain potassium-40! 🍌☢️",
        "Hot water freezes faster than cold water — it's called the Mpemba effect! 🧊",
    ],
    "ocean": [
        "The ocean floor has mountains taller than Mount Everest! 🏔️🌊",
        "More people have been to the Moon than to the deepest part of the ocean! 🌙",
        "There's enough gold in the ocean to give every person on Earth 9 pounds of it! 💰",
    ],
    "default": [
        "Your brain uses about 20% of your body's energy, even though it's only 2% of your weight! 🧠",
        "A bolt of lightning is five times hotter than the surface of the Sun! ⚡",
        "The inventor of the Pringles can is buried in one! 😄",
    ],
}


async def fun_fact(args: dict) -> dict:
    """Share an interesting fact."""
    topic = args.get("topic", "").lower()

    # Find the best matching category
    for category, facts in FACTS.items():
        if category in topic or topic in category:
            return {"text": f"**Fun fact!** {random.choice(facts)}"}

    # Check if topic words appear in any fact
    for category, facts in FACTS.items():
        matching = [f for f in facts if topic in f.lower()]
        if matching:
            return {"text": f"**Fun fact!** {random.choice(matching)}"}

    # Default
    all_facts = [f for facts in FACTS.values() for f in facts]
    return {"text": f"**Fun fact!** {random.choice(all_facts)}"}
