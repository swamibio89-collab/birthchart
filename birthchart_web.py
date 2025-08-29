import swisseph as swe
from datetime import datetime, timedelta
import pytz
from flask import Flask, request, render_template_string
from geopy.geocoders import Nominatim
from timezonefinder import TimezoneFinder

app = Flask(__name__)

PLANET_ABBR = {
    "Sun": "Su", "Moon": "Mo", "Mars": "Ma", "Mercury": "Me", "Jupiter": "Ju", "Venus": "Ve",
    "Saturn": "Sa", "Rahu": "Ra", "Ketu": "Ke", "Lagna": "As", "Maandi": "m"
}
PLANETS = [
    ("Sun", swe.SUN), ("Moon", swe.MOON), ("Mars", swe.MARS), ("Mercury", swe.MERCURY),
    ("Jupiter", swe.JUPITER), ("Venus", swe.VENUS), ("Saturn", swe.SATURN),
    ("Rahu", swe.MEAN_NODE), ("Ketu", swe.TRUE_NODE)
]
RASI_LABELS = [
    "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
    "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"
]
RASI_LORDS = {
    "Mesha": "Mars", "Vrishabha": "Venus", "Mithuna": "Mercury", "Karka": "Moon",
    "Simha": "Sun", "Kanya": "Mercury", "Tula": "Venus", "Vrischika": "Mars",
    "Dhanu": "Jupiter", "Makara": "Saturn", "Kumbha": "Saturn", "Meena": "Jupiter"
}
NAKSHATRA_NAMES = [
    "Ashwini", "Bharani", "Krittika", "Rohini", "Mrigashira", "Ardra", "Punarvasu",
    "Pushya", "Ashlesha", "Magha", "Purva Phalguni", "Uttara Phalguni", "Hasta",
    "Chitra", "Swati", "Vishakha", "Anuradha", "Jyeshtha", "Mula",
    "Purva Ashadha", "Uttara Ashadha", "Shravana", "Dhanishta", "Shatabhisha",
    "Purva Bhadrapada", "Uttara Bhadrapada", "Revati"
]
VIM_SEQ = ["Ketu", "Venus", "Sun", "Moon", "Mars", "Rahu", "Jupiter", "Saturn", "Mercury"]
VIM_YEARS = {
    "Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7, "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17
}
NAKSHATRA_LORDS = VIM_SEQ * 3  # 27

MAANDI_DEGREES = {
    "Sunday":   (156, 240),
    "Monday":   (132, 216),
    "Tuesday":  (108, 192),
    "Wednesday":(84, 336),
    "Thursday": (60, 312),
    "Friday":   (36, 288),
    "Saturday": (12, 264),
}

def get_julian_day(year, month, day, hour, minute, second, tz_str):
    tz = pytz.timezone(tz_str)
    dt = tz.localize(datetime(year, month, day, hour, minute, second))
    ut_dt = dt.astimezone(pytz.utc)
    jd = swe.julday(ut_dt.year, ut_dt.month, ut_dt.day,
                    ut_dt.hour + ut_dt.minute/60 + ut_dt.second/3600)
    return jd, dt, ut_dt

def dms(degree):
    d = int(degree)
    m = int((degree - d) * 60)
    s = (degree - d - m/60) * 3600
    return d, m, s

def format_dms(degree):
    d, m, s = dms(degree)
    return f"{d}° {abs(m):02d}' {abs(s):05.2f}\""

def format_rasi_dms(longitude):
    deg_in_rasi = longitude % 30
    d, m, s = dms(deg_in_rasi)
    return f"{d}° {abs(m):02d}' {abs(s):05.2f}\""

def get_ascendant_and_houses(jd, lat, lon):
    swe.set_sid_mode(swe.SIDM_KRISHNAMURTI)
    house_cusps, ascmc = swe.houses_ex(jd, lat, lon, b'A', flags=swe.FLG_SIDEREAL)
    ascendant = ascmc[0]
    return ascendant, house_cusps

def get_planet_positions(jd):
    swe.set_sid_mode(swe.SIDM_KRISHNAMURTI)
    positions = {}
    for name, code in PLANETS:
        if name == "Ketu":
            rahu_lon = positions["Rahu"]
            ketu_lon = (rahu_lon + 180) % 360
            positions["Ketu"] = ketu_lon
        else:
            ret, flag = swe.calc_ut(jd, code, swe.FLG_SIDEREAL)
            positions[name] = ret[0]
    return positions

def get_rasi_from_longitude(longitude):
    rasi_num = int(longitude // 30)
    rasi_name = RASI_LABELS[rasi_num]
    return rasi_num, rasi_name

def get_nakshatra_pada(longitude):
    nakshatra_size = 360 / 27
    pada_size = nakshatra_size / 4
    nak_num = int(longitude // nakshatra_size)
    nak_name = NAKSHATRA_NAMES[nak_num]
    pada_num = int((longitude % nakshatra_size) // pada_size) + 1
    return nak_name, pada_num

def get_navamsa_rasi(longitude):
    sign_num = int(longitude // 30)
    offset = longitude % 30
    pada = int(offset // (30 / 9))
    navamsa_sign = (sign_num * 9 + pada) % 12
    return navamsa_sign, RASI_LABELS[navamsa_sign]

def get_maandi_longitude(sun_long, weekday, hour, minute, dt, lat, lon):
    try:
        import astral
        from astral.sun import sun
        from astral import LocationInfo
        city = LocationInfo(latitude=lat, longitude=lon)
        sun_times = sun(city.observer, date=dt.date())
        sunrise = sun_times["sunrise"].astimezone(dt.tzinfo)
        sunset = sun_times["sunset"].astimezone(dt.tzinfo)
        curr_time = dt
        is_morning = curr_time < sunset
    except Exception:
        is_morning = hour < 18
    key = "Sunday Monday Tuesday Wednesday Thursday Friday Saturday".split()[weekday]
    add_deg = MAANDI_DEGREES[key][0 if is_morning else 1]
    maandi_long = (sun_long + add_deg) % 360
    return maandi_long

def get_full_planet_table(planet_positions, ascendant, maandi_long):
    result = []
    lagna_rasi_num, lagna_rasi = get_rasi_from_longitude(ascendant)
    lagna_nav_num, lagna_nav = get_navamsa_rasi(ascendant)
    lagna_nak, lagna_pada = get_nakshatra_pada(ascendant)
    result.append({
        "Body": "Lagna",
        "Longitude": format_dms(ascendant),
        "RasiDegree": format_rasi_dms(ascendant),
        "Nakshatra": lagna_nak,
        "Pada": lagna_pada,
        "Rasi": lagna_rasi,
        "Navamsa": lagna_nav
    })
    for planet, lon in planet_positions.items():
        rasi_num, rasi = get_rasi_from_longitude(lon)
        nav_num, navamsa = get_navamsa_rasi(lon)
        nakshatra, pada = get_nakshatra_pada(lon)
        result.append({
            "Body": planet,
            "Longitude": format_dms(lon),
            "RasiDegree": format_rasi_dms(lon),
            "Nakshatra": nakshatra,
            "Pada": pada,
            "Rasi": rasi,
            "Navamsa": navamsa
        })
    rasi_num, rasi = get_rasi_from_longitude(maandi_long)
    nav_num, navamsa = get_navamsa_rasi(maandi_long)
    nakshatra, pada = get_nakshatra_pada(maandi_long)
    result.append({
        "Body": "Maandi",
        "Longitude": format_dms(maandi_long),
        "RasiDegree": format_rasi_dms(maandi_long),
        "Nakshatra": nakshatra,
        "Pada": pada,
        "Rasi": rasi,
        "Navamsa": navamsa
    })
    return result

def get_chart_boxes(planet_positions, ascendant, maandi_long, chart_type="rasi"):
    boxes = [[] for _ in range(12)]
    if chart_type == "rasi":
        lagna_rasi_num, _ = get_rasi_from_longitude(ascendant)
        boxes[lagna_rasi_num].append(PLANET_ABBR["Lagna"])
    elif chart_type == "navamsa":
        lagna_nav_num, _ = get_navamsa_rasi(ascendant)
        boxes[lagna_nav_num].append(PLANET_ABBR["Lagna"])
    for planet, lon in planet_positions.items():
        if chart_type == "rasi":
            box_num, _ = get_rasi_from_longitude(lon)
        else:
            box_num, _ = get_navamsa_rasi(lon)
        abbr = PLANET_ABBR[planet]
        boxes[box_num].append(abbr)
    if chart_type == "rasi":
        box_num, _ = get_rasi_from_longitude(maandi_long)
    else:
        box_num, _ = get_navamsa_rasi(maandi_long)
    boxes[box_num].append(PLANET_ABBR["Maandi"])
    return boxes

def html_south_chart(boxes, chart_title="Rasi"):
    sign_order = [11, 0, 1, 2,
                  10, None, None, 3,
                  9, None, None, 4,
                  8, 7, 6, 5]
    center_label = chart_title
    table = '<table class="south-chart">'
    idx = 0
    for r in range(4):
        table += "<tr>"
        for c in range(4):
            si = sign_order[idx]
            idx += 1
            if si is None:
                if r == 1 and c == 1:
                    table += f'<td class="center" rowspan="2" colspan="2" style="font-size:22px;font-weight:bold;text-align:center;vertical-align:middle;">{center_label}</td>'
            else:
                planets = " ".join(boxes[si])
                table += f'<td><b>{RASI_LABELS[si]}</b><br>{planets}</td>'
        table += "</tr>"
    table += "</table>"
    return table

def get_bhava_table(ascendant, planet_positions, maandi_long):
    lagna_rasi_num, lagna_rasi = get_rasi_from_longitude(ascendant)
    houses = []
    for i in range(12):
        rasi_num = (lagna_rasi_num + i) % 12
        rasi_name = RASI_LABELS[rasi_num]
        lord = RASI_LORDS[rasi_name]
        cusp_degree = (rasi_num * 30) + 15
        nav_num, navamsa_sign = get_navamsa_rasi(cusp_degree)
        houses.append({
            "House": i+1,
            "Rasi": rasi_name,
            "Lord": lord,
            "Navamsa": navamsa_sign
        })
    return houses

def vimshottari_tree(moon_longitude, birthdt, levels=5):
    def period(years, start):
        return (start, start + timedelta(days=years*365.25))
    nak_num = int(moon_longitude // (360/27))
    seq_idx = nak_num % 9
    nakshatra_size = 360/27
    lord = VIM_SEQ[seq_idx]
    dasa_years = VIM_YEARS[lord]
    pos_in_nak = (moon_longitude % nakshatra_size) / nakshatra_size
    elapsed = pos_in_nak * dasa_years
    remaining = dasa_years - elapsed
    out = []
    dasha_seq = VIM_SEQ * 3
    dasha_idx = seq_idx
    dasha_start = birthdt
    for d in range(9):
        dasha_lord = dasha_seq[dasha_idx % 9]
        dasha_len = VIM_YEARS[dasha_lord]
        if d == 0:
            dasha_len = remaining
        dasha_end = dasha_start + timedelta(days=dasha_len*365.25)
        dasha_item = {
            "lord": dasha_lord, "start": dasha_start, "end": dasha_end, "years": dasha_len, "children": []
        }
        if levels >= 2:
            bhukti_idx = dasha_idx
            bhukti_start = dasha_start
            for b in range(9):
                bhukti_lord = dasha_seq[(bhukti_idx + b) % 9]
                bhukti_len = dasha_len * VIM_YEARS[bhukti_lord] / 120
                bhukti_end = bhukti_start + timedelta(days=bhukti_len*365.25)
                bhukti_item = {
                    "lord": bhukti_lord, "start": bhukti_start, "end": bhukti_end, "years": bhukti_len, "children": []
                }
                if levels >= 3:
                    antar_start = bhukti_start
                    for a in range(9):
                        antar_lord = dasha_seq[(bhukti_idx + a) % 9]
                        antar_len = bhukti_len * VIM_YEARS[antar_lord] / 120
                        antar_end = antar_start + timedelta(days=antar_len*365.25)
                        antar_item = {
                            "lord": antar_lord, "start": antar_start, "end": antar_end, "years": antar_len, "children": []
                        }
                        if levels >= 4:
                            sukshma_start = antar_start
                            for s in range(9):
                                sukshma_lord = dasha_seq[(bhukti_idx + s) % 9]
                                sukshma_len = antar_len * VIM_YEARS[sukshma_lord] / 120
                                sukshma_end = sukshma_start + timedelta(days=sukshma_len*365.25)
                                sukshma_item = {
                                    "lord": sukshma_lord, "start": sukshma_start, "end": sukshma_end, "years": sukshma_len, "children": []
                                }
                                if levels >= 5:
                                    prana_start = sukshma_start
                                    for p in range(9):
                                        prana_lord = dasha_seq[(bhukti_idx + p) % 9]
                                        prana_len = sukshma_len * VIM_YEARS[prana_lord] / 120
                                        prana_end = prana_start + timedelta(days=prana_len*365.25)
                                        prana_item = {
                                            "lord": prana_lord, "start": prana_start, "end": prana_end, "years": prana_len
                                        }
                                        sukshma_item.setdefault("children", []).append(prana_item)
                                        prana_start = prana_end
                                antar_item.setdefault("children", []).append(sukshma_item)
                                sukshma_start = sukshma_end
                        bhukti_item.setdefault("children", []).append(antar_item)
                        antar_start = antar_end
                dasha_item.setdefault("children", []).append(bhukti_item)
                bhukti_start = bhukti_end
        out.append(dasha_item)
        dasha_start = dasha_end
        dasha_idx += 1
    return out

import pandas as pd

def calculate_ashtakavarga(jd, planet_positions):
    """
    Computes a simplified Sarva Ashtakavarga:
    - Each planet gets points (bindus) for signs based on sample logic.
    - Returns: DataFrame (12 signs x 8 planets) and Sarva Ashtakavarga total.
    You can replace the inner logic with classical rules as you build out!
    """
    planets = ["Sun", "Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Lagna"]
    rasi_labels = [
        "Mesha", "Vrishabha", "Mithuna", "Karka", "Simha", "Kanya",
        "Tula", "Vrischika", "Dhanu", "Makara", "Kumbha", "Meena"
    ]
    # Initialize all to zero
    av_table = {rasi: {p: 0 for p in planets} for rasi in rasi_labels}

    # Simplest demo: give 1 point to the sign the planet is in
    for p in planets:
        if p == "Lagna":
            lag_long = planet_positions["Lagna"]
            rasi_num, rasi = get_rasi_from_longitude(lag_long)
            av_table[rasi][p] += 1
        elif p in planet_positions:
            lon = planet_positions[p]
            rasi_num, rasi = get_rasi_from_longitude(lon)
            av_table[rasi][p] += 1

    # Compute Sarva Ashtakavarga (total per sign)
    sarva = []
    for rasi in rasi_labels:
        total = sum(av_table[rasi].values())
        av_table[rasi]["Total"] = total
        sarva.append(total)

    # Convert to DataFrame for HTML/table
    df = pd.DataFrame(av_table).T[planets + ["Total"]]
    df.index.name = "Sign"
    return df

@app.route("/", methods=["GET", "POST"])
def main():
    output = ""
    planet_table = []
    dasa_table = []
    bhava_table = []
    vim_tree = []
    resolved_loc = ""
    if request.method == "POST":
        dob = request.form.get("dob")
        tob = request.form.get("tob")
        location_str = request.form.get("location")
        if dob and tob and location_str:
            geolocator = Nominatim(user_agent="astro_kp_app")
            loc = geolocator.geocode(location_str)
            if not loc:
                return "Could not find location. Please enter a valid city/town.", 400
            lat, lon = loc.latitude, loc.longitude
            tf = TimezoneFinder()
            tz_str = tf.timezone_at(lat=lat, lng=lon) or "Asia/Kolkata"
            resolved_loc = f"{loc.address} (lat: {lat:.4f}, lon: {lon:.4f}, tz: {tz_str})"
            jd, dt, ut_dt = get_julian_day(*map(int, dob.split('-')), *map(int, tob.split(':')), 0, tz_str)
            ascendant, house_cusps = get_ascendant_and_houses(jd, lat, lon)
            planet_positions = get_planet_positions(jd)
            sun_long = planet_positions["Sun"]
            weekday = dt.weekday()
            weekday = (weekday+1)%7
            hour = dt.hour
            minute = dt.minute
            maandi_long = get_maandi_longitude(sun_long, weekday, hour, minute, dt, lat, lon)
            planet_table = get_full_planet_table(planet_positions, ascendant, maandi_long)
            rasi_boxes = get_chart_boxes(planet_positions, ascendant, maandi_long, chart_type="rasi")
            nav_boxes = get_chart_boxes(planet_positions, ascendant, maandi_long, chart_type="navamsa")
            rasi_chart_html = html_south_chart(rasi_boxes, chart_title="Rasi")
            navamsa_chart_html = html_south_chart(nav_boxes, chart_title="Navamsa")
            moon_long = planet_positions["Moon"]
            dasa_tree = vimshottari_tree(moon_long, dt, levels=5)
            vim_tree = dasa_tree
            dasa_table = vimshottari_tree(moon_long, dt, levels=1)
            bhava_table = get_bhava_table(ascendant, planet_positions, maandi_long)
            output = f"""
            <button onclick="window.print()" style="margin:12px 0;padding:6px 20px;font-size:16px;">Export to PDF / Print</button>
            <div style="color:#277; margin-bottom:10px;"><b>Resolved Location:</b> {resolved_loc}</div>
            <h3>KP (Lahiri new) South Indian Style Rasi and Navamsa Charts</h3>
            <div style="display:flex;gap:16px;">{rasi_chart_html}{navamsa_chart_html}</div>
            """
    html = '''
    <script>
    function toggleNode(id) {
      var node = document.getElementById('node-' + id);
      var arrow = document.getElementById('arrow-' + id);
      if(node.style.display === 'none') {
        node.style.display = 'block';
        if(arrow) arrow.textContent = '▼';
      } else {
        node.style.display = 'none';
        if(arrow) arrow.textContent = '▶';
      }
    }
    </script>
    {% macro render_vim_tree_js(items, parent_id='d', level=1) -%}
      <ul style="margin-left:{{level*12}}px;list-style:none;padding-left:0;">
        {% for i in items %}
          {% set node_id = parent_id ~ '-' ~ loop.index %}
          <li>
            <span onclick="toggleNode('{{node_id}}')" style="cursor:pointer;user-select:none;">
              <b>
                <span id="arrow-{{node_id}}">▶</span>
                {{i.lord}}
              </b>
            </span>
            <span style="font-size:90%;margin-left:4px;">
              {{i.start.strftime("%Y-%m-%d")}} to {{i.end.strftime("%Y-%m-%d")}} ({{i.years|round(2)}}y)
            </span>
            {% if i.children %}
            <div id="node-{{node_id}}" style="display:none;">
              {{ render_vim_tree_js(i.children, node_id, level+1) }}
            </div>
            {% endif %}
          </li>
        {% endfor %}
      </ul>
    {%- endmacro %}
    <html>
    <head>
    <title>KP South Indian Birth Chart</title>
    <style>
    @media print { body { background: #fff; } .south-chart td, .planet-table td, .dasa-table td { font-size:13px !important;}}
    body { font-family: Arial, sans-serif; margin:30px;}
    table.south-chart {border-collapse:collapse;}
    table.south-chart td { width:90px; height:70px; border:2px solid #388e3c; text-align:center; vertical-align:top; font-size:18px; background:#fcffe6;}
    table.south-chart .empty { background:none; border:none;}
    .center { background:#f8eab8 !important; border:2px solid #888 !important;}
    table.planet-table {border-collapse:collapse;margin-top:18px;}
    table.planet-table td, table.planet-table th {border:1px solid #888;padding:3px 7px;}
    table.dasa-table {border-collapse:collapse;margin-top:12px;}
    table.dasa-table td, table.dasa-table th {border:1px solid #888;padding:2px 7px;}
    </style>
    </head>
    <body>
    <h2>KP/Lahiri South Indian Birth Chart Generator</h2>
    <form method="post" style="margin-bottom:20px;">
      <label>Date of Birth:</label>
      <input type="date" name="dob" required>
      <label>Time (24h):</label>
      <input type="time" name="tob" required step="60">
      <label>Location (type any city/town/village):</label>
      <input type="text" name="location" required style="width:300px;" placeholder="e.g. Chennai, India">
      <button type="submit">Generate Chart</button>
    </form>
    <hr>
    {{output|safe}}
    {% if planet_table %}
    <h3>Planet & Lagna Details</h3>
    <table class="planet-table">
      <tr>
        <th>Body</th><th>Longitude</th><th>Degree in Rasi</th><th>Nakshatra</th><th>Pada</th><th>Rasi</th><th>Navamsa</th>
      </tr>
      {% for p in planet_table %}
      <tr>
        <td>{{p.Body}}</td>
        <td>{{p.Longitude}}</td>
        <td>{{p.RasiDegree}}</td>
        <td>{{p.Nakshatra}}</td>
        <td>{{p.Pada}}</td>
        <td>{{p.Rasi}}</td>
        <td>{{p.Navamsa}}</td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}
    {% if dasa_table %}
    <h3>Vimshottari Mahadasha</h3>
    <table class="dasa-table">
      <tr>
        <th>Dasha Lord</th><th>Years</th><th>Start</th><th>End</th>
      </tr>
      {% for d in dasa_table %}
      <tr>
        <td>{{d.lord}}</td>
        <td>{{d.years|round(2)}}</td>
        <td>{{d.start.strftime("%Y-%m-%d")}}</td>
        <td>{{d.end.strftime("%Y-%m-%d")}}</td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}
    {% if bhava_table %}
    <h3>Bhava/House Table</h3>
    <table class="planet-table">
      <tr>
        <th>House</th><th>Rasi</th><th>Lord</th><th>Navamsa Sign</th>
      </tr>
      {% for h in bhava_table %}
      <tr>
        <td>{{h.House}}</td>
        <td>{{h.Rasi}}</td>
        <td>{{h.Lord}}</td>
        <td>{{h.Navamsa}}</td>
      </tr>
      {% endfor %}
    </table>
    {% endif %}
    {% if vim_tree %}
    <h3>Full Vimshottari Dasha → Bhukti → Antara → Sukshma → Prana<br>
      <small style="font-weight:normal;">(Click ▶ to expand/▼ to collapse. Up to 120 years.)</small></h3>
    <div style="font-family:monospace;font-size:15px;">
      {{ render_vim_tree_js(vim_tree) }}
    </div>
    {% endif %}
    </body>
    </html>
    '''
    return render_template_string(
        html,
        output=output,
        planet_table=planet_table,
        dasa_table=dasa_table[0]['children'] if dasa_table and dasa_table[0].get('children') else [],
        bhava_table=bhava_table,
        vim_tree=vim_tree
    )

def get_birthchart_full_output(dob, tob, place, query_datetime):
    """
    Returns a dict with all major birth chart, house, planet, dasa, and maandi details.
    dob: 'YYYY-MM-DD'
    tob: 'HH:MM'
    place: city/town/village string
    query_datetime: datetime object (for dasa calculation as of today)
    """
    from geopy.geocoders import Nominatim
    from timezonefinder import TimezoneFinder
    import pytz

    # Parse input
    geolocator = Nominatim(user_agent="astro_kp_app")
    loc = geolocator.geocode(place)
    if not loc:
        raise Exception("Could not find location. Please enter a valid city/town/village.")
    lat, lon = loc.latitude, loc.longitude
    tf = TimezoneFinder()
    tz_str = tf.timezone_at(lat=lat, lng=lon) or "Asia/Kolkata"
    dt = pytz.timezone(tz_str).localize(datetime.strptime(f"{dob} {tob}", "%d/%m/%Y %H:%M"))

    weekday = dt.weekday()
    weekday = (weekday + 1) % 7
    hour = dt.hour
    minute = dt.minute
    jd, dt, ut_dt = get_julian_day(dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second, tz_str)
    ascendant, house_cusps = get_ascendant_and_houses(jd, lat, lon)
    planet_positions = get_planet_positions(jd)
    sun_long = planet_positions["Sun"]
    maandi_long = get_maandi_longitude(sun_long, weekday, hour, minute, dt, lat, lon)
    planet_table = get_full_planet_table(planet_positions, ascendant, maandi_long)
    bhava_table = get_bhava_table(ascendant, planet_positions, maandi_long)
    moon_long = planet_positions["Moon"]
    vim_tree = vimshottari_tree(moon_long, dt, levels=3) # Dasa, Bhukti, Antar
    # Find dasa, bhukti, antar at query_datetime
    dasa = bhukti = antar = None
    for d in vim_tree:
        if d["start"] <= query_datetime <= d["end"]:
            dasa = d["lord"]
            for b in d["children"]:
                if b["start"] <= query_datetime <= b["end"]:
                    bhukti = b["lord"]
                    for a in b["children"]:
                        if a["start"] <= query_datetime <= a["end"]:
                            antar = a["lord"]
                            break
                    break
            break

    # Compose output
    output = {
        "input_birth_datetime": dt.strftime("%Y-%m-%d %H:%M"),
        "input_place": place,
        "latitude": lat,
        "longitude": lon,
        "tz_str": tz_str,
        "ascendant": ascendant,
        "ascendant_rasi": get_rasi_from_longitude(ascendant)[1],
        "ascendant_degree": format_rasi_dms(ascendant),
        "sun_longitude": planet_positions["Sun"],
        "sun_rasi": get_rasi_from_longitude(planet_positions["Sun"])[1],
        "sun_degree": format_rasi_dms(planet_positions["Sun"]),
        "moon_longitude": planet_positions["Moon"],
        "moon_rasi": get_rasi_from_longitude(planet_positions["Moon"])[1],
        "moon_degree": format_rasi_dms(planet_positions["Moon"]),
        "venus_longitude": planet_positions["Venus"],
        "venus_rasi": get_rasi_from_longitude(planet_positions["Venus"])[1],
        "venus_degree": format_rasi_dms(planet_positions["Venus"]),
        "mercury_longitude": planet_positions["Mercury"],
        "mercury_rasi": get_rasi_from_longitude(planet_positions["Mercury"])[1],
        "mercury_degree": format_rasi_dms(planet_positions["Mercury"]),
        "saturn_longitude": planet_positions["Saturn"],
        "saturn_rasi": get_rasi_from_longitude(planet_positions["Saturn"])[1],
        "saturn_degree": format_rasi_dms(planet_positions["Saturn"]),
        "maandi_longitude": maandi_long,
        "maandi_rasi": get_rasi_from_longitude(maandi_long)[1],
        "maandi_degree": format_rasi_dms(maandi_long),
        "planets_table": planet_table,
        "houses": bhava_table,
        "dasa": dasa,
        "bhukti": bhukti,
        "antar": antar
    }
    return output

# --- local runner (optional; OK to keep even on Render) ---
if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
