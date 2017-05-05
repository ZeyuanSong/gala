# coding: utf-8

from __future__ import division, print_function

# Standard library
import warnings
import inspect

# Third-party
import astropy.coordinates as coord
import astropy.units as u
import numpy as np
from six import string_types

# Project
from . import representation_nd as rep_nd
from .plot import plot_projections
from ..coordinates import vgal_to_hel
from ..units import UnitSystem, DimensionlessUnitSystem, _greek_letters
from ..util import atleast_2d

__all__ = ['PhaseSpacePosition', 'CartesianPhaseSpacePosition']

class PhaseSpacePosition(object):
    """
    Represents phase-space positions, i.e. positions and conjugate momenta
    (velocities).

    The class can be instantiated with Astropy representation objects (e.g.,
    :class:`~astropy.coordinates.CartesianRepresentation`), Astropy
    :class:`~astropy.units.Quantity` objects, or plain Numpy arrays.

    If passing in representation objects, the default representation is taken to
    be the class that is passed in.

    If passing in Quantity or Numpy array instances for both position and
    velocity, they are assumed to be Cartesian. Array inputs are interpreted as
    dimensionless quantities. The input position and velocity objects can have
    an arbitrary number of (broadcastable) dimensions. For Quantity or array
    inputs, the first axis (0) has special meaning::

        - `axis=0` is the coordinate dimension (e.g., x, y, z for Cartesian)

    So if the input position array, `pos`, has shape `pos.shape = (3, 100)`,
    this would represent 100 3D positions (`pos[0]` is `x`, `pos[1]` is `y`,
    etc.). The same is true for velocity.

    Parameters
    ----------
    pos : :class:`~astropy.coordinates.BaseRepresentation`, :class:`~astropy.units.Quantity`, array_like
        Positions. If a numpy array (e.g., has no units), this will be
        stored as a dimensionless :class:`~astropy.units.Quantity`. See
        the note above about the assumed meaning of the axes of this object.
    vel : :class:`~astropy.coordinates.BaseDifferential`, :class:`~astropy.units.Quantity`, array_like
        Velocities. If a numpy array (e.g., has no units), this will be
        stored as a dimensionless :class:`~astropy.units.Quantity`. See
        the note above about the assumed meaning of the axes of this object.
    frame : :class:`~gala.potential.FrameBase` (optional)
        The reference frame of the input phase-space positions.

    TODO
    ----
    Add a hack to support array input when ndim < 3?

    """
    def __init__(self, pos, vel, frame=None):

        if not isinstance(pos, coord.BaseRepresentation):
            # assume Cartesian if not specified
            if not hasattr(pos, 'unit'):
                pos = pos * u.one

            # 3D coordinates get special treatment
            ndim = pos.shape[0]
            if ndim == 3:
                # TODO: HACK: until this stuff is in astropy core
                if isinstance(pos, coord.BaseRepresentation):
                    kw = [(k,getattr(pos,k)) for k in pos.components]
                    pos = getattr(coord, pos.__class__.__name__)(**kw)

                else:
                    pos = coord.CartesianRepresentation(pos)

            else:
                pos = rep_nd.NDCartesianRepresentation(*pos)

        else:
            ndim = 3

        if not isinstance(vel, coord.BaseDifferential):

            if ndim == 3:
                default_rep = pos.__class__
                default_rep_name = default_rep.get_name().capitalize()
                Diff = getattr(coord, default_rep_name+'Differential')

            else:
                Diff = rep_nd.NDCartesianDifferential

            # assume representation is same as pos if not specified
            if not hasattr(vel, 'unit'):
                vel = vel * u.one

            vel = Diff(*vel)

        else:
            # assume Cartesian if not specified
            if not hasattr(vel, 'unit'):
                vel = vel * u.one

        # make sure shape is the same
        if pos.shape != vel.shape:
            raise ValueError("Position and velocity must have the same shape "
                             "{} vs {}".format(pos.shape, vel.shape))

        from ..potential.frame import FrameBase
        if frame is not None and not isinstance(frame, FrameBase):
            raise TypeError("Input reference frame must be a FrameBase "
                            "subclass instance.")

        self.pos = pos
        self.vel = vel
        self.frame = frame
        self.ndim = ndim

        for name in pos.components:
            setattr(self, name, getattr(pos,name))

        for name in vel.components:
            setattr(self, name, getattr(vel,name))

    def __getitem__(self, slyce):
        return self.__class__(pos=self.pos[slyce],
                              vel=self.vel[slyce],
                              frame=self.frame)

    # ------------------------------------------------------------------------
    # Convert from Cartesian to other representations
    #
    def represent_as(self, Representation):
        """
        Represent the position and velocity of the orbit in an alternate
        coordinate system. Supports any of the Astropy coordinates
        representation classes.

        Parameters
        ----------
        Representation : :class:`~astropy.coordinates.BaseRepresentation`
            The class for the desired representation.

        Returns
        -------
        new_psp : `gala.dynamics.PhaseSpacePosition`
        """

        if self.ndim != 3:
            raise ValueError("Can only change representation for "
                             "ndim=3 instances.")

        # get the name of the desired representation
        if not isinstance(Representation, string_types):
            name = Representation.get_name()
        Representation = coord.representation.REPRESENTATION_CLASSES[name]
        base_name = Representation.__name__[:-len('Representation')]
        Differential = getattr(coord, base_name+'Differential')

        new_pos = self.pos.represent_as(Representation)
        new_vel = self.vel.represent_as(Differential, self.pos)

        return self.__class__(pos=new_pos,
                              vel=new_vel,
                              frame=self.frame)

    def to_frame(self, frame, current_frame=None, **kwargs):
        """
        Transform to a new reference frame.

        Parameters
        ----------
        frame : `~gala.potential.FrameBase`
            The frame to transform to.
        current_frame : `gala.potential.CFrameBase`
            The current frame the phase-space position is in.
        **kwargs
            Any additional arguments are passed through to the individual frame
            transformation functions (see:
            `~gala.potential.frame.builtin.transformations`).

        Returns
        -------
        psp : `gala.dynamics.CartesianPhaseSpacePosition`
            The phase-space position in the new reference frame.

        """

        from ..potential.frame.builtin import transformations as frame_trans

        if ((inspect.isclass(frame) and issubclass(frame, coord.BaseCoordinateFrame)) or
                isinstance(frame, coord.BaseCoordinateFrame)):
            import warnings
            warnings.warn("This function now expects a "
                          "`gala.potential.FrameBase` instance. To transform to"
                          " an Astropy coordinate frame, use the "
                          "`.to_coord_frame()` method instead.",
                          DeprecationWarning)
            return self.to_coord_frame(frame=frame, **kwargs)

        if self.frame is None and current_frame is None:
            raise ValueError("If no frame was specified when this {} was "
                             "initialized, you must pass the current frame in "
                             "via the current_frame argument to transform to a "
                             "new frame.")

        elif self.frame is not None and current_frame is None:
            current_frame = self.frame

        name1 = current_frame.__class__.__name__.rstrip('Frame').lower()
        name2 = frame.__class__.__name__.rstrip('Frame').lower()
        func_name = "{}_to_{}".format(name1, name2)

        if not hasattr(frame_trans, func_name):
            raise ValueError("Unsupported frame transformation: {} to {}"
                             .format(current_frame, frame))
        else:
            trans_func = getattr(frame_trans, func_name)

        pos, vel = trans_func(current_frame, frame, self, **kwargs)
        return PhaseSpacePosition(pos=pos, vel=vel, frame=frame)

    def to_coord_frame(self, frame,
                       galactocentric_frame=None, vcirc=None, vlsr=None):
        """
        Transform the orbit from Galactocentric, cartesian coordinates to
        Heliocentric coordinates in the specified Astropy coordinate frame.

        Parameters
        ----------
        frame : :class:`~astropy.coordinates.BaseCoordinateFrame`
        galactocentric_frame : :class:`~astropy.coordinates.Galactocentric`
        vcirc : :class:`~astropy.units.Quantity`
            Circular velocity of the Sun. Passed to velocity transformation.
        vlsr : :class:`~astropy.units.Quantity`
            Velocity of the Sun relative to the LSR. Passed to
            velocity transformation.

        Returns
        -------
        c : :class:`~astropy.coordinates.BaseCoordinateFrame`
            An instantiated coordinate frame.
        v : tuple
            A tuple of velocities represented as
            :class:`~astropy.units.Quantity` objects.

        """

        if self.ndim != 3:
            raise ValueError("Can only change representation for "
                             "ndim=3 instances.")

        if galactocentric_frame is None:
            galactocentric_frame = coord.Galactocentric()

        kw = dict()
        kw['galactocentric_frame'] = galactocentric_frame
        kw['vcirc'] = vcirc
        kw['vlsr'] = vlsr

        # first we need to turn the position into a Galactocentric instance
        gc_c = galactocentric_frame.realize_frame(self.pos)
        c = gc_c.transform_to(frame)
        rep = c.represent_as(c.representation)

        # HACK: until there is easy lookup for Differential classes
        new_Diff = getattr(coord, rep.__class__.__name__[:-14] + 'Differential')
        vxyz = self.vel.represent_as(coord.CartesianDifferential,
                                     base=rep).d_xyz
        v = vgal_to_hel(c, vxyz, galactocentric_frame=galactocentric_frame)
        v = v.represent_as(new_Diff, base=rep)

        return c, v

    # Convenience attributes
    @property
    def cartesian(self):
        return self.represent_as(coord.CartesianRepresentation)

    @property
    def spherical(self):
        return self.represent_as(coord.SphericalRepresentation)

    @property
    def spherical(self):
        return self.represent_as(coord.PhysicsSphericalRepresentation)

    @property
    def cylindrical(self):
        return self.represent_as(coord.CylindricalRepresentation)

    # Pseudo-backwards compatibility
    def w(self, units=None):
        """
        This returns a single array containing the phase-space positions.

        Parameters
        ----------
        units : `~gala.units.UnitSystem` (optional)
            The unit system to represent the position and velocity in
            before combining into the full array.

        Returns
        -------
        w : `~numpy.ndarray`
            A numpy array of all positions and velocities, without units.
            Will have shape ``(2*ndim,...)``.

        """
        if self.ndim == 3:
            cart = self.cartesian
        else:
            cart = self

        xyz = cart.pos.xyz
        d_xyz = cart.vel.d_xyz

        x_unit = xyz.unit
        v_unit = d_xyz.unit
        if ((units is None or isinstance(units, DimensionlessUnitSystem)) and
                (x_unit == u.one and v_unit == u.one)):
            units = DimensionlessUnitSystem()

        elif units is None:
            raise ValueError("A UnitSystem must be provided.")

        x = xyz.decompose(units).value
        if x.ndim < 2:
            x = atleast_2d(x, insert_axis=1)

        v = d_xyz.decompose(units).value
        if v.ndim < 2:
            v = atleast_2d(v, insert_axis=1)

        return np.vstack((x,v))

    @classmethod
    def from_w(cls, w, units=None, **kwargs):
        """
        Create a {name} object from a single array specifying positions
        and velocities. This is mainly for backwards-compatibility and
        it is not recommended for new users.

        Parameters
        ----------
        w : array_like
            The array of phase-space positions.
        units : `~gala.units.UnitSystem` (optional)
            The unit system that the input position+velocity array, ``w``,
            is represented in.
        **kwargs
            Any aditional keyword arguments passed to the class initializer.

        Returns
        -------
        obj : `~gala.dynamics.{name}`

        """.format(name=cls.__name__)

        w = np.array(w)

        ndim = w.shape[0]//2
        pos = w[:ndim]
        vel = w[ndim:]

        # TODO: this is bad form - UnitSystem should know what to do with a
        # Dimensionless
        if units is not None and not isinstance(units, DimensionlessUnitSystem):
            units = UnitSystem(units)
            pos = pos*units['length']
            vel = vel*units['length']/units['time'] # from _core_units

        return cls(pos=pos, vel=vel, **kwargs)

    # ------------------------------------------------------------------------
    # Computed dynamical quantities
    #
    def kinetic_energy(self):
        r"""
        The kinetic energy *per unit mass*:

        .. math::

            E_K = \frac{1}{2} \, |\boldsymbol{v}|^2

        Returns
        -------
        E : :class:`~astropy.units.Quantity`
            The kinetic energy.
        """
        return 0.5 * self.vel.norm()**2

    def potential_energy(self, potential):
        r"""
        The potential energy *per unit mass*:

        .. math::

            E_\Phi = \Phi(\boldsymbol{q})

        Parameters
        ----------
        potential : `gala.potential.PotentialBase`
            The potential object to compute the energy from.

        Returns
        -------
        E : :class:`~astropy.units.Quantity`
            The potential energy.
        """
        # TODO: check that potential ndim is consistent with here
        return potential.value(self)

    def energy(self, hamiltonian):
        r"""
        The total energy *per unit mass* (e.g., kinetic + potential):

        Parameters
        ----------
        hamiltonian : `gala.potential.Hamiltonian`
            The Hamiltonian object to evaluate the energy.

        Returns
        -------
        E : :class:`~astropy.units.Quantity`
            The total energy.
        """
        from ..potential import PotentialBase
        if isinstance(hamiltonian, PotentialBase):
            from ..potential import Hamiltonian

            warnings.warn("This function now expects a `Hamiltonian` instance "
                          "instead of  a `PotentialBase` subclass instance. If "
                          "you are using a static reference frame, you just "
                          "need to pass your potential object in to the "
                          "Hamiltonian constructor to use, e.g., "
                          "Hamiltonian(potential).", DeprecationWarning)

            hamiltonian = Hamiltonian(hamiltonian)

        return hamiltonian(self)

    def angular_momentum(self):
        r"""
        Compute the angular momentum for the phase-space positions contained
        in this object::

        .. math::

            \boldsymbol{{L}} = \boldsymbol{{q}} \times \boldsymbol{{p}}

        See :ref:`shape-conventions` for more information about the shapes of
        input and output objects.

        Returns
        -------
        L : :class:`~astropy.units.Quantity`
            Array of angular momentum vectors.

        Examples
        --------

            >>> import numpy as np
            >>> import astropy.units as u
            >>> pos = np.array([1., 0, 0]) * u.au
            >>> vel = np.array([0, 2*np.pi, 0]) * u.au/u.yr
            >>> w = PhaseSpacePosition(pos, vel)
            >>> w.angular_momentum()
            <Quantity [ 0.        , 0.        , 6.28318531] AU2 / yr>
        """
        cart = self.represent_as(coord.CartesianRepresentation)
        return cart.pos.cross(cart.vel).xyz

    # ------------------------------------------------------------------------
    # Misc. useful methods
    #
    def _plot_prepare(self, components, units, rep):
        """
        Prepare the ``PhaseSpacePosition`` or subclass for passing to a plotting
        routine to plot all projections of the object.
        """

        # re-represent if specified and ndim==3
        if rep is None:
            rep = coord.CartesianRepresentation

        if self.ndim == 3:
            # allow user to specify representation
            obj = self.represent_as(rep)

        else:
            obj = self

        # components to plot
        if components is None:
            components = obj.pos.components
        n_comps = len(components)

        # if units not specified, get units from the components
        if units is not None:
            if isinstance(units, u.UnitBase):
                units = [units]*n_comps # global unit

            elif len(units) != n_comps:
                raise ValueError('You must specify a unit for each axis, or a '
                                 'single unit for all axes.')

        labels = []
        x = []
        for i,name in enumerate(components):
            val = getattr(obj, name)

            if units is not None:
                val = val.to(units[i])
                unit = units[i]
            else:
                unit = val.unit

            if val.unit != u.one:
                uu = unit.to_string(format='latex_inline')
                unit_str = ' [{}]'.format(uu)
            else:
                unit_str = ''

            # Figure out how to fancy display the component name
            if name.startswith('d_'):
                dot = True
                name = name[2:]
            else:
                dot = False

            if name in _greek_letters:
                name = r"\{}".format(name)

            if dot:
                name = "\dot{{{}}}".format(name)

            labels.append('${}$'.format(name) + unit_str)
            x.append(val.value)

        return x, labels

    def plot(self, components=None, units=None, rep=None, **kwargs):
        """
        Plot the positions in all projections. This is a wrapper around
        `~gala.dynamics.plot_projections` for fast access and quick
        visualization. All extra keyword arguments are passed to that function
        (the docstring for this function is included here for convenience).

        Parameters
        ----------
        components : iterable (optional)
            A list of component names (strings) to plot. By default, this is the
            Cartesian positions ``['x', 'y', 'z']``. To plot Cartesian
            velocities, pass in the velocity component names
            ``['d_x', 'd_y', 'd_z']``.
        units : `~astropy.units.UnitBase`, iterable (optional)
            A single unit or list of units to display the components in.
        rep : str, `~astropy.coordinates.BaseRepresentation` (optional)
            The representation to plot the object in. Default is cartesian.
        relative_to : bool (optional)
            Plot the values relative to this value or values.
        autolim : bool (optional)
            Automatically set the plot limits to be something sensible.
        axes : array_like (optional)
            Array of matplotlib Axes objects.
        subplots_kwargs : dict (optional)
            Dictionary of kwargs passed to :func:`~matplotlib.pyplot.subplots`.
        labels : iterable (optional)
            List or iterable of axis labels as strings. They should correspond to
            the dimensions of the input orbit.
        plot_function : callable (optional)
            The ``matplotlib`` plot function to use. By default, this is
            :func:`~matplotlib.pyplot.scatter`, but can also be, e.g.,
            :func:`~matplotlib.pyplot.plot`.
        **kwargs
            All other keyword arguments are passed to the ``plot_function``.
            You can pass in any of the usual style kwargs like ``color=...``,
            ``marker=...``, etc.

        Returns
        -------
        fig : `~matplotlib.Figure`

        """

        try:
            import matplotlib.pyplot as plt
        except ImportError:
            msg = 'matplotlib is required for visualization.'
            raise ImportError(msg)

        x,labels = self._plot_prepare(components=components,
                                      units=units,
                                      rep=rep)

        default_kwargs = {
            'marker': '.',
            'labels': labels,
            'plot_function': plt.scatter,
            'autolim': False
        }

        for k,v in default_kwargs.items():
            kwargs[k] = kwargs.get(k, v)

        fig = plot_projections(x, **kwargs)

        if rep is None or rep.get_name() == 'cartesian':
            for ax in fig.axes:
                ax.set(aspect='equal', adjustable='datalim')

        return fig

    # ------------------------------------------------------------------------
    # Display
    #
    def __repr__(self):
        return "<{}, shape={}, frame={}>".format(self.__class__.__name__,
                                                 self.pos.shape,
                                                 self.frame)

    def __str__(self):
        return "pos={}\nvel={}".format(self.pos, self.vel)

    # ------------------------------------------------------------------------
    # Shape and size
    #

    @property
    def shape(self):
        """
        .. warning::

            This is *not* the shape of the position or velocity
            arrays. That is accessed by doing ``obj.pos.shape``.

        Returns
        -------
        shp : tuple

        """
        return self.pos.shape

class CartesianPhaseSpacePosition(PhaseSpacePosition):

    def __init__(self, pos, vel, frame=None):

        warnings.warn("This class is now deprecated! Use the general interface "
                      "provided by PhaseSpacePosition instead.",
                      DeprecationWarning)

        super(CartesianPhaseSpacePosition, self).__init__(pos, vel, frame=frame)
