/* 
 * timg_starpu.c
 *
 * Implements a basic TIMG pipeline using StarPU and the ARL C Wrappers.
 *
 * Very much a work-in-progress with a lot of duplicated code.
 * TODO: Some code sourced directly from ffi_demo.c, need to create separate
 * source/header for all helper routines.
 *
 * Author: Arjen Tamerus <at748@cam.ac.uk>
 */

#include <Python.h>
#include <starpu.h>
#include <stdarg.h>
#include <stdio.h>

#include "../src/arlwrap.h"
#include "../src/wrap_support.h"
#include "timg_pu_routines.h"

int main(int argc, char *argv[]) {
	/* BEGIN setup_stolen_from_ffi_demo */
	int *shape = malloc(4*sizeof(int));
	int status;
	int nvis;

	double cellsize = 5e-4;
	char config_name[] = "LOWBD2-CORE";

	ARLVis *vt;
	ARLVis *vtmp;

	ARLConf *lowconfig;

	starpu_init(NULL);

	Py_Initialize();

	// We need this macro (+ END macro), otherwise starpu's pthreads will deadlock
	// when trying to get the Python interpreter lock
	Py_BEGIN_ALLOW_THREADS

	lowconfig = allocate_arlconf_default(config_name);

	nvis = lowconfig->nbases * lowconfig->nfreqs * lowconfig->ntimes;

	vt = allocate_vis_data(lowconfig->npol, nvis);
	vtmp = allocate_vis_data(lowconfig->npol, nvis);

	/* END setup_stolen_from_ffi_demo */

	starpu_data_handle_t create_visibility_h[2];
	starpu_variable_data_register(&create_visibility_h[0], STARPU_MAIN_RAM,
			(uintptr_t)lowconfig, sizeof(ARLConf));
	starpu_variable_data_register(&create_visibility_h[1], STARPU_MAIN_RAM,
			(uintptr_t)vt, sizeof(ARLVis));

	struct starpu_task *vis_task = create_task(&create_visibility_cl, create_visibility_h);
	starpu_task_submit(vis_task);

	helper_get_image_shape(lowconfig->freqs, cellsize, shape);

	Image *model = allocate_image(shape);
	Image *m31image = allocate_image(shape);
	Image *dirty = allocate_image(shape);
	Image *psf = allocate_image(shape);
	Image *comp = allocate_image(shape);
	Image *residual = allocate_image(shape);
	Image *restored = allocate_image(shape);

	/* Data handles are used by StarPU to pass (pointers to) data to the codelets
	 * at execution time */
	starpu_data_handle_t test_image_h[4];

	/* For now we are just passing the raw pointers to required data, to the data
	 * handle. Most routines expect pointers at this point, and it is easier to
	 * handle edge cases in the codelets, keeping this main routine clean. */
	starpu_variable_data_register(&test_image_h[0], STARPU_MAIN_RAM,
			(uintptr_t)lowconfig->freqs, sizeof(double*));
	starpu_variable_data_register(&test_image_h[1], STARPU_MAIN_RAM,
			(uintptr_t)&cellsize, sizeof(double));
	starpu_variable_data_register(&test_image_h[2], STARPU_MAIN_RAM,
			(uintptr_t)(vt->phasecentre), sizeof(char*));
	starpu_variable_data_register(&test_image_h[3], STARPU_MAIN_RAM,
			(uintptr_t)m31image, sizeof(Image));

	// Input: pointer to starpu codelet, data handle
	// Create the StarPU task: associate the data in the data handle with the
	// routine specified in the codelet, and schedule the task for execution.
	struct starpu_task *test_img_task = create_task(&create_test_image_cl, test_image_h);

	// For some reason (TODO: find out why) StarPU is not getting data
	// dependencies right, so we need to explicitly tell it about task
	// dependencies instead.
	starpu_task_declare_deps_array(test_img_task, 1, &vis_task);

	// Hand the task over to 
	starpu_task_submit(test_img_task);

	// Use macros for data registration frome here, to improve readability
	starpu_data_handle_t pred_handle[3];
	SVDR(pred_handle, 0, vt, sizeof(ARLVis));
	SVDR(pred_handle, 1, m31image, sizeof(Image));
	SVDR(pred_handle, 2, vtmp, sizeof(ARLVis));

	struct starpu_task *pred_task = create_task(&predict_2d_cl, pred_handle);
	starpu_task_declare_deps_array(pred_task, 1, &test_img_task);
	starpu_task_submit(pred_task);

	starpu_data_handle_t create_from_vis_handle[2];
	SVDR(create_from_vis_handle, 0, vtmp, sizeof(ARLVis));
	SVDR(create_from_vis_handle, 1, model, sizeof(Image));
	struct starpu_task *create_from_vis_task = create_task(&create_from_visibility_cl, create_from_vis_handle);
	starpu_task_declare_deps_array(create_from_vis_task, 1, &pred_task);
	starpu_task_submit(create_from_vis_task);

	bool invert_false = false;
	bool invert_true = true;

	double *sumwt = malloc(sizeof(double));

	starpu_data_handle_t invert_2d_dirty_handle[5];
	SVDR(invert_2d_dirty_handle, 0, vt, sizeof(ARLVis));
	SVDR(invert_2d_dirty_handle, 1, model, sizeof(Image));
	SVDR(invert_2d_dirty_handle, 2, &invert_false, sizeof(bool));
	SVDR(invert_2d_dirty_handle, 3, dirty, sizeof(Image));
	SVDR(invert_2d_dirty_handle, 4, sumwt, sizeof(double));

	struct starpu_task *invert_2d_dirty_task = create_task(&invert_2d_cl, invert_2d_dirty_handle);
	starpu_task_declare_deps_array(invert_2d_dirty_task, 1, &create_from_vis_task);
	starpu_task_submit(invert_2d_dirty_task);

	starpu_data_handle_t invert_2d_psf_handle[5];
	SVDR(invert_2d_psf_handle, 0, vt, sizeof(ARLVis));
	SVDR(invert_2d_psf_handle, 1, model, sizeof(Image));
	SVDR(invert_2d_psf_handle, 2, &invert_true, sizeof(bool));
	SVDR(invert_2d_psf_handle, 3, psf, sizeof(Image));
	SVDR(invert_2d_psf_handle, 4, sumwt, sizeof(double));

	struct starpu_task *invert_2d_psf_task = create_task(&invert_2d_cl, invert_2d_psf_handle);
	starpu_task_declare_deps_array(invert_2d_psf_task, 1, &invert_2d_dirty_task);
	starpu_task_submit(invert_2d_psf_task);

	starpu_data_handle_t deconvolve_cube_handle[4];
	SVDR(deconvolve_cube_handle, 0, dirty, sizeof(Image));
	SVDR(deconvolve_cube_handle, 1, psf, sizeof(Image));
	SVDR(deconvolve_cube_handle, 2, comp, sizeof(Image));
	SVDR(deconvolve_cube_handle, 3, residual, sizeof(Image));

	struct starpu_task *deconvolve_cube_task = create_task(&deconvolve_cube_cl, deconvolve_cube_handle);
	starpu_task_declare_deps_array(deconvolve_cube_task, 1, &invert_2d_psf_task);
	starpu_task_submit(deconvolve_cube_task);

	starpu_data_handle_t restore_cube_handle[4];
	SVDR(restore_cube_handle, 0, comp, sizeof(Image));
	SVDR(restore_cube_handle, 1, psf, sizeof(Image));
	SVDR(restore_cube_handle, 2, residual, sizeof(Image));
	SVDR(restore_cube_handle, 3, restored, sizeof(Image));

	struct starpu_task *restore_cube_task = create_task(&restore_cube_cl, restore_cube_handle);
	starpu_task_declare_deps_array(restore_cube_task, 1, &deconvolve_cube_task);
	starpu_task_submit(restore_cube_task);


	// === Terminate ===

	// Wait for all tasks to complete
	starpu_task_wait_for_all();

	// FITS files output
	status = mkdir("results", S_IRWXU | S_IRWXG | S_IROTH | S_IXOTH);
	status = export_image_to_fits_c(m31image, "results/m31image.fits");
	status = export_image_to_fits_c(dirty, "results/dirty.fits");
	status = export_image_to_fits_c(psf, "results/psf.fits");
	status = export_image_to_fits_c(residual, "results/residual.fits");
	status = export_image_to_fits_c(restored, "results/restored.fits");
	status = export_image_to_fits_c(comp, "results/solution.fits");

	starpu_shutdown();

	// Close the threading-enabling macro
	Py_END_ALLOW_THREADS

	return 0;
}
