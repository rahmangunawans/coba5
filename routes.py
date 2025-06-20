from datetime import datetime, timedelta
from flask import render_template, request, redirect, url_for, flash, abort, session, Response
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash
from app import app, db
from models import User, Anime, AnimeSeason, AnimeEpisode, Movie, MoviePart, WatchHistory, Subscription
from forms import LoginForm, RegisterForm, AnimeForm, AnimeSeasonForm, AnimeEpisodeForm, MovieForm, MoviePartForm

# Subscription plans configuration
SUBSCRIPTION_PLANS = {
    'regular': {
        1: 30000,   # 1 month
        3: 100000,  # 3 months
        12: 350000  # 1 year
    },
    'vip': {
        1: 40000,   # 1 month
        3: 120000,  # 3 months
        12: 440000  # 1 year
    }
}

@app.route('/')
def index():
    # Get featured content
    featured_anime = Anime.query.order_by(Anime.rating.desc()).limit(6).all()
    featured_movies = Movie.query.order_by(Movie.rating.desc()).limit(6).all()
    
    return render_template('index.html', 
                         featured_anime=featured_anime, 
                         featured_movies=featured_movies)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user and user.check_password(form.password.data):
            # Ensure admin users have VIP access
            user.ensure_admin_vip()
            login_user(user)
            next_page = request.args.get('next')
            return redirect(next_page) if next_page else redirect(url_for('dashboard'))
        flash('Invalid username or password', 'error')
    elif request.method == 'POST':
        # Debug form validation errors
        app.logger.debug(f'Form validation failed: {form.errors}')
        flash('Please check your input', 'error')
    
    return render_template('login.html', form=form)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    form = RegisterForm()
    if form.validate_on_submit():
        user = User(username=form.username.data, email=form.email.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('Registration successful!', 'success')
        return redirect(url_for('login'))
    
    return render_template('register.html', form=form)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    # Get user's watch history
    recent_history = WatchHistory.query.filter_by(user_id=current_user.id)\
                                      .order_by(WatchHistory.watched_at.desc())\
                                      .limit(10).all()
    
    # Get recommended content based on watch history
    watched_genres = db.session.query(Anime.genre)\
                              .join(AnimeSeason, Anime.id == AnimeSeason.anime_id)\
                              .join(AnimeEpisode, AnimeSeason.id == AnimeEpisode.season_id)\
                              .join(WatchHistory, WatchHistory.content_id == AnimeEpisode.id)\
                              .filter(WatchHistory.user_id == current_user.id,
                                     WatchHistory.content_type == 'anime')\
                              .distinct().all()
    
    recommended_anime = []
    if watched_genres:
        genres = [g[0] for g in watched_genres if g[0]]
        recommended_anime = Anime.query.filter(Anime.genre.in_(genres))\
                                     .order_by(Anime.rating.desc())\
                                     .limit(6).all()
    
    return render_template('dashboard.html', 
                         recent_history=recent_history,
                         recommended_anime=recommended_anime)

@app.route('/subscription')
@login_required
def subscription():
    return render_template('subscription.html', plans=SUBSCRIPTION_PLANS)

@app.route('/subscribe/<plan_type>/<int:duration>')
@login_required
def subscribe(plan_type, duration):
    if plan_type not in SUBSCRIPTION_PLANS or duration not in SUBSCRIPTION_PLANS[plan_type]:
        flash('Invalid subscription plan', 'error')
        return redirect(url_for('subscription'))
    
    amount = SUBSCRIPTION_PLANS[plan_type][duration]
    
    # In a real application, this would integrate with a payment processor
    # For now, we'll just activate the subscription
    
    # Update user subscription
    current_user.subscription_type = plan_type
    current_user.subscription_expires = datetime.utcnow() + timedelta(days=duration * 30)
    
    # Create subscription record
    subscription = Subscription(
        user_id=current_user.id,
        plan_type=plan_type,
        duration_months=duration,
        amount_paid=amount,
        expires_at=current_user.subscription_expires
    )
    
    db.session.add(subscription)
    db.session.commit()
    
    flash(f'Successfully subscribed to {plan_type.title()} plan!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/browse')
@login_required
def browse():
    content_type = request.args.get('type', 'anime')
    genre = request.args.get('genre', '')
    search = request.args.get('search', '')
    
    if content_type == 'anime':
        query = Anime.query
        if genre:
            query = query.filter(Anime.genre.contains(genre))
        if search:
            query = query.filter(Anime.title.contains(search))
        content = query.order_by(Anime.created_at.desc()).all()
    else:
        query = Movie.query
        if genre:
            query = query.filter(Movie.genre.contains(genre))
        if search:
            query = query.filter(Movie.title.contains(search))
        content = query.order_by(Movie.created_at.desc()).all()
    
    return render_template('browse.html', 
                         content=content, 
                         content_type=content_type,
                         current_genre=genre,
                         current_search=search)

@app.route('/watch/anime/<int:anime_id>')
@login_required
def watch_anime(anime_id):
    anime = Anime.query.get_or_404(anime_id)
    season_id = request.args.get('season', type=int)
    episode_id = request.args.get('episode', type=int)
    
    if not season_id:
        season_id = anime.seasons[0].id if anime.seasons else None
    
    season = AnimeSeason.query.get_or_404(season_id) if season_id else None
    
    if not episode_id and season:
        episode_id = season.episodes[0].id if season.episodes else None
    
    episode = AnimeEpisode.query.get_or_404(episode_id) if episode_id else None
    
    # Check if user can watch (free tier limitations)
    if not current_user.can_watch_episode():
        flash('You have reached your daily episode limit. Upgrade to continue watching!', 'warning')
        return redirect(url_for('subscription'))
    
    if episode:
        # Record watch history
        current_user.increment_episodes_watched()
        
        history = WatchHistory(
            user_id=current_user.id,
            content_type='anime',
            content_id=episode.id
        )
        db.session.add(history)
        db.session.commit()
    
    # Get recommended anime (same genre or high rated)
    recommended_anime = []
    if anime.genre:
        # Get anime with same genre
        genre_words = anime.genre.split(',')[0].strip()
        recommended_anime = Anime.query.filter(
            Anime.id != anime_id,
            Anime.genre.ilike(f'%{genre_words}%')
        ).order_by(Anime.rating.desc()).limit(6).all()
        
    # If not enough recommendations, get top rated anime
    if len(recommended_anime) < 6:
        additional = Anime.query.filter(
            Anime.id != anime_id
        ).order_by(Anime.rating.desc()).limit(6 - len(recommended_anime)).all()
        recommended_anime.extend(additional)
    
    return render_template('watch_anime_new.html', 
                         anime=anime, 
                         season=season, 
                         episode=episode,
                         recommended_anime=recommended_anime)

@app.route('/watch/movie/<int:movie_id>')
@login_required
def watch_movie(movie_id):
    movie = Movie.query.get_or_404(movie_id)
    
    # For free users, limit movie watching to 10 minutes
    watch_limit = 10 if (current_user.subscription_type or 'free') == 'free' else None
    
    # Record watch history
    history = WatchHistory(
        user_id=current_user.id,
        content_type='movie',
        content_id=movie.id,
        watch_time_minutes=watch_limit or movie.duration_minutes
    )
    db.session.add(history)
    db.session.commit()
    
    # Get recommended movies (same genre or high rated)
    recommended_movies = []
    if movie.genre:
        # Get movies with same genre
        genre_words = movie.genre.split(',')[0].strip()
        recommended_movies = Movie.query.filter(
            Movie.id != movie_id,
            Movie.genre.ilike(f'%{genre_words}%')
        ).order_by(Movie.rating.desc()).limit(6).all()
        
    # If not enough recommendations, get top rated movies
    if len(recommended_movies) < 6:
        additional = Movie.query.filter(
            Movie.id != movie_id
        ).order_by(Movie.rating.desc()).limit(6 - len(recommended_movies)).all()
        recommended_movies.extend(additional)
    
    return render_template('watch_movie_new.html', 
                         movie=movie, 
                         watch_limit=watch_limit,
                         recommended_movies=recommended_movies)

# Admin routes
@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin:
        abort(403)
    
    anime_count = Anime.query.count()
    movie_count = Movie.query.count()
    user_count = User.query.count()
    
    return render_template('admin/dashboard.html',
                         anime_count=anime_count,
                         movie_count=movie_count,
                         user_count=user_count)

@app.route('/admin/add_content')
@login_required
def admin_add_content():
    if not current_user.is_admin:
        abort(403)
    return render_template('admin/add_content.html')

@app.route('/admin/add_anime', methods=['GET', 'POST'])
@login_required
def admin_add_anime():
    if not current_user.is_admin:
        abort(403)
    
    form = AnimeForm()
    if form.validate_on_submit():
        anime = Anime(
            title=form.title.data,
            description=form.description.data,
            genre=form.genre.data,
            rating=form.rating.data or 0.0,
            year=form.year.data,
            poster_url=form.poster_url.data,
            trailer_url=form.trailer_url.data
        )
        db.session.add(anime)
        db.session.commit()
        flash('Anime added successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, content_type='anime')

@app.route('/admin/add_movie', methods=['GET', 'POST'])
@login_required
def admin_add_movie():
    if not current_user.is_admin:
        abort(403)
    
    form = MovieForm()
    if form.validate_on_submit():
        movie = Movie(
            title=form.title.data,
            description=form.description.data,
            genre=form.genre.data,
            rating=form.rating.data or 0.0,
            year=form.year.data,
            duration_minutes=form.duration_minutes.data,
            poster_url=form.poster_url.data,
            trailer_url=form.trailer_url.data
        )
        db.session.add(movie)
        db.session.commit()
        flash('Movie added successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, content_type='movie')

@app.route('/admin/anime/<int:anime_id>/add_season', methods=['GET', 'POST'])
@login_required
def admin_add_season(anime_id):
    if not current_user.is_admin:
        abort(403)
    
    anime = Anime.query.get_or_404(anime_id)
    form = AnimeSeasonForm()
    
    if form.validate_on_submit():
        season = AnimeSeason(
            anime_id=anime.id,
            season_number=form.season_number.data,
            title=form.title.data
        )
        db.session.add(season)
        db.session.commit()
        flash('Season added successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, anime=anime, content_type='season')

@app.route('/admin/season/<int:season_id>/add_episode', methods=['GET', 'POST'])
@login_required
def admin_add_episode(season_id):
    if not current_user.is_admin:
        abort(403)
    
    season = AnimeSeason.query.get_or_404(season_id)
    form = AnimeEpisodeForm()
    
    if form.validate_on_submit():
        episode = AnimeEpisode(
            season_id=season.id,
            episode_number=form.episode_number.data,
            title=form.title.data,
            description=form.description.data,
            stream_url=form.stream_url.data,
            duration_minutes=form.duration_minutes.data,
            thumbnail_url=form.thumbnail_url.data
        )
        db.session.add(episode)
        db.session.commit()
        flash('Episode added successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, season=season, content_type='episode')

@app.route('/admin/add_movie_part/<int:movie_id>', methods=['GET', 'POST'])
@login_required
def admin_add_movie_part(movie_id):
    if not current_user.is_admin:
        abort(403)
    
    movie = Movie.query.get_or_404(movie_id)
    form = MoviePartForm()
    
    if form.validate_on_submit():
        movie_part = MoviePart(
            movie_id=movie.id,
            part_number=form.part_number.data,
            title=form.title.data,
            duration_minutes=form.duration_minutes.data,
            stream_url=form.stream_url.data
        )
        db.session.add(movie_part)
        db.session.commit()
        flash('Movie part added successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, movie=movie, content_type='movie_part')

@app.route('/admin/manage_content')
@login_required
def admin_manage_content():
    if not current_user.is_admin:
        abort(403)
    
    anime_list = Anime.query.order_by(Anime.created_at.desc()).all()
    movie_list = Movie.query.order_by(Movie.created_at.desc()).all()
    
    return render_template('admin/manage_content.html', 
                         anime_list=anime_list, 
                         movie_list=movie_list)

@app.route('/admin/edit_anime/<int:anime_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_anime(anime_id):
    if not current_user.is_admin:
        abort(403)
    
    anime = Anime.query.get_or_404(anime_id)
    form = AnimeForm(obj=anime)
    
    if form.validate_on_submit():
        form.populate_obj(anime)
        db.session.commit()
        flash('Anime updated successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, content_type='anime', edit_mode=True)

@app.route('/admin/edit_movie/<int:movie_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_movie(movie_id):
    if not current_user.is_admin:
        abort(403)
    
    movie = Movie.query.get_or_404(movie_id)
    form = MovieForm(obj=movie)
    
    if form.validate_on_submit():
        form.populate_obj(movie)
        db.session.commit()
        flash('Movie updated successfully!', 'success')
        return redirect(url_for('admin_manage_content'))
    
    return render_template('admin/add_content.html', form=form, content_type='movie', edit_mode=True)

@app.route('/admin/delete_anime/<int:anime_id>', methods=['POST'])
@login_required
def admin_delete_anime(anime_id):
    if not current_user.is_admin:
        abort(403)
    
    anime = Anime.query.get_or_404(anime_id)
    db.session.delete(anime)
    db.session.commit()
    flash('Anime deleted successfully!', 'success')
    return redirect(url_for('admin_manage_content'))

@app.route('/admin/delete_movie/<int:movie_id>', methods=['POST'])
@login_required
def admin_delete_movie(movie_id):
    if not current_user.is_admin:
        abort(403)
    
    movie = Movie.query.get_or_404(movie_id)
    db.session.delete(movie)
    db.session.commit()
    flash('Movie deleted successfully!', 'success')
    return redirect(url_for('admin_manage_content'))

# Episode management routes
@app.route('/admin/edit_episode/<int:episode_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_episode(episode_id):
    if not current_user.is_admin:
        abort(403)
    
    episode = AnimeEpisode.query.get_or_404(episode_id)
    form = AnimeEpisodeForm(obj=episode)
    
    if form.validate_on_submit():
        form.populate_obj(episode)
        db.session.commit()
        flash('Episode updated successfully!', 'success')
        return redirect(url_for('admin_manage_episodes', season_id=episode.season_id))
    
    return render_template('admin/edit_episode.html', form=form, episode=episode)

@app.route('/admin/delete_episode/<int:episode_id>', methods=['POST'])
@login_required
def admin_delete_episode(episode_id):
    if not current_user.is_admin:
        abort(403)
    
    episode = AnimeEpisode.query.get_or_404(episode_id)
    season_id = episode.season_id
    db.session.delete(episode)
    db.session.commit()
    flash('Episode deleted successfully!', 'success')
    return redirect(url_for('admin_manage_episodes', season_id=season_id))

@app.route('/admin/manage_episodes/<int:season_id>')
@login_required
def admin_manage_episodes(season_id):
    if not current_user.is_admin:
        abort(403)
    
    season = AnimeSeason.query.get_or_404(season_id)
    episodes = AnimeEpisode.query.filter_by(season_id=season_id).order_by(AnimeEpisode.episode_number).all()
    
    return render_template('admin/manage_episodes.html', season=season, episodes=episodes)

# Movie part management routes
@app.route('/admin/edit_movie_part/<int:part_id>', methods=['GET', 'POST'])
@login_required
def admin_edit_movie_part(part_id):
    if not current_user.is_admin:
        abort(403)
    
    part = MoviePart.query.get_or_404(part_id)
    form = MoviePartForm(obj=part)
    
    if form.validate_on_submit():
        form.populate_obj(part)
        db.session.commit()
        flash('Movie part updated successfully!', 'success')
        return redirect(url_for('admin_manage_movie_parts', movie_id=part.movie_id))
    
    return render_template('admin/edit_movie_part.html', form=form, part=part)

@app.route('/admin/delete_movie_part/<int:part_id>', methods=['POST'])
@login_required
def admin_delete_movie_part(part_id):
    if not current_user.is_admin:
        abort(403)
    
    part = MoviePart.query.get_or_404(part_id)
    movie_id = part.movie_id
    db.session.delete(part)
    db.session.commit()
    flash('Movie part deleted successfully!', 'success')
    return redirect(url_for('admin_manage_movie_parts', movie_id=movie_id))

@app.route('/admin/manage_movie_parts/<int:movie_id>')
@login_required
def admin_manage_movie_parts(movie_id):
    if not current_user.is_admin:
        abort(403)
    
    movie = Movie.query.get_or_404(movie_id)
    parts = MoviePart.query.filter_by(movie_id=movie_id).order_by(MoviePart.part_number).all()
    
    return render_template('admin/manage_movie_parts.html', movie=movie, parts=parts)

@app.route('/stream/anime/<int:episode_id>')
@login_required
def stream_anime_episode(episode_id):
    episode = AnimeEpisode.query.get_or_404(episode_id)
    
    # Check subscription limits for free users
    if (current_user.subscription_type or 'free') == 'free':
        if not current_user.can_watch_episode():
            flash('Daily episode limit reached. Upgrade to watch more!', 'warning')
            return redirect(url_for('subscription'))
        current_user.increment_episodes_watched()
    
    # Record watch history
    history = WatchHistory(
        user_id=current_user.id,
        content_type='anime',
        content_id=episode.id,
        watch_time_minutes=episode.duration_minutes or 25
    )
    db.session.add(history)
    db.session.commit()
    
    # Use iframe player
    return render_template('iframe_player.html',
                         stream_url=episode.stream_url,
                         title=f"{episode.season.anime.title} - S{episode.season.season_number}E{episode.episode_number}",
                         content_type='episode',
                         content_id=episode.id,
                         episode=episode)

@app.route('/stream/movie/<int:part_id>')
@login_required
def stream_movie_part(part_id):
    part = MoviePart.query.get_or_404(part_id)
    
    # For free users, limit movie watching to 10 minutes
    watch_limit = 10 if (current_user.subscription_type or 'free') == 'free' else None
    
    # Record watch history
    history = WatchHistory(
        user_id=current_user.id,
        content_type='movie',
        content_id=part.movie.id,
        watch_time_minutes=watch_limit or part.duration_minutes
    )
    db.session.add(history)
    db.session.commit()
    
    # Use iframe player
    return render_template('iframe_player.html',
                         stream_url=part.stream_url,
                         title=f"{part.movie.title} - Part {part.part_number}",
                         content_type='movie_part',
                         content_id=part.id,
                         movie_part=part)

@app.route('/player')
@login_required
def iframe_player():
    stream_url = request.args.get('stream_url')
    title = request.args.get('title', 'Unknown')
    content_type = request.args.get('content_type')
    content_id = request.args.get('content_id')
    
    if not stream_url:
        flash('No stream URL provided', 'error')
        return redirect(url_for('browse'))
    
    episode = None
    movie_part = None
    
    if content_type == 'episode' and content_id:
        episode = AnimeEpisode.query.get(content_id)
    elif content_type == 'movie_part' and content_id:
        movie_part = MoviePart.query.get(content_id)
    
    return render_template('iframe_player.html',
                         stream_url=stream_url,
                         title=title,
                         content_type=content_type,
                         content_id=content_id,
                         episode=episode,
                         movie_part=movie_part)

@app.route('/stream/embedded')
@login_required
def stream_embedded():
    url = request.args.get('url')
    title = request.args.get('title', 'Unknown')
    content_type = request.args.get('content_type')
    content_id = request.args.get('content_id')
    
    episode = None
    movie_part = None
    
    if content_type == 'episode' and content_id:
        episode = AnimeEpisode.query.get(content_id)
    elif content_type == 'movie_part' and content_id:
        movie_part = MoviePart.query.get(content_id)
    
    return render_template('stream_embedded.html', 
                         url=url, 
                         title=title,
                         content_type=content_type,
                         episode=episode,
                         movie_part=movie_part)

@app.route('/stream_torrent/<info_hash>')
def stream_torrent_data(info_hash):
    from real_torrent_streamer import real_streamer
    
    # Get streaming response
    stream_response = real_streamer.get_stream_response(info_hash)
    
    if stream_response:
        return stream_response
    else:
        return "Stream not available", 404

@app.route('/torrent_info')
def get_torrent_info():
    from real_torrent_streamer import real_streamer
    
    magnet_url = request.args.get('magnet')
    if not magnet_url:
        return {"error": "No magnet URL provided"}, 400
    
    # Parse magnet link
    magnet_info = real_streamer.parse_magnet_link(magnet_url)
    
    if magnet_info:
        return {
            "status": "success",
            "stream_url": f"/stream_torrent/{magnet_info['info_hash']}",
            "info": magnet_info
        }
    else:
        return {"error": "Failed to parse torrent"}, 400

@app.route('/start_torrent_download')
def start_torrent_download():
    from real_torrent_streamer import real_streamer
    
    magnet_url = request.args.get('magnet')
    if not magnet_url:
        return {"error": "No magnet URL provided"}, 400
    
    # Parse and start download
    magnet_info = real_streamer.parse_magnet_link(magnet_url)
    if not magnet_info:
        return {"error": "Invalid magnet link"}, 400
    
    download_info = real_streamer.start_progressive_download(magnet_info)
    if download_info:
        return {
            "status": "success",
            "message": "Download started",
            "info_hash": magnet_info['info_hash']
        }
    else:
        return {"error": "Failed to start download"}, 500

@app.route('/torrent_progress/<info_hash>')
def get_torrent_progress(info_hash):
    from real_torrent_streamer import real_streamer
    
    progress = real_streamer.get_download_progress(info_hash)
    if progress:
        return progress
    else:
        return {"error": "Torrent not found"}, 404

@app.context_processor
def inject_user():
    return dict(current_user=current_user)
