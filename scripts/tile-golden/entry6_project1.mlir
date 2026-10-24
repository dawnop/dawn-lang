cuda_tile.module @m {
  entry @entry6_project1(%arg0: tile<ptr<f32>>, %arg1: tile<ptr<f32>>, %arg2: tile<ptr<f32>>, %arg3: tile<ptr<f32>>, %arg4: tile<f32>, %arg5: tile<i32>) optimization_hints=<sm_86 = {occupancy = 2}> {
    %0 = make_token : token
    %1 = constant <i32: 1> : tile<i32>
    %2 = constant <i32: 2> : tile<i32>
    %3 = assume div_by<16>, %arg0 : tile<ptr<f32>>
    %4 = make_tensor_view %3, shape = [1, 4, 4], strides = [16, 4, 1] : tensor_view<1x4x4xf32, strides=[16, 4, 1]>
    %5 = make_partition_view %4 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>
    %6, %7, %8 = get_tile_block_id : tile<i32>
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12, %13, %14 = get_tile_block_id : tile<i32>
    %15, %16 = load_view_tko weak %5[%8, %9, %13] token=%0 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x2x4xf32>, token
    %17 = reshape %15 : tile<1x2x4xf32> -> tile<2x4xf32>
    %18 = assume div_by<16>, %arg1 : tile<ptr<f32>>
    %19 = make_tensor_view %18, shape = [1, 4, 4], strides = [16, 4, 1] : tensor_view<1x4x4xf32, strides=[16, 4, 1]>
    %20 = make_partition_view %19 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>
    %21, %22 = load_view_tko weak %20[%8, %9, %13] token=%0 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x2x4xf32>, token
    %23 = reshape %21 : tile<1x2x4xf32> -> tile<2x4xf32>
    %24 = constant <f32: 2.0> : tile<2x4xf32>
    %25 = mulf %23, %24 rounding<nearest_even> : tile<2x4xf32>
    %26 = addf %17, %25 rounding<nearest_even> : tile<2x4xf32>
    %27 = assume div_by<16>, %arg2 : tile<ptr<f32>>
    %28 = make_tensor_view %27, shape = [1, 4, 4], strides = [16, 4, 1] : tensor_view<1x4x4xf32, strides=[16, 4, 1]>
    %29 = make_partition_view %28 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>
    %30, %31 = load_view_tko weak %29[%8, %9, %13] token=%0 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> tile<1x2x4xf32>, token
    %32 = reshape %30 : tile<1x2x4xf32> -> tile<2x4xf32>
    %33 = constant <f32: 4.0> : tile<2x4xf32>
    %34 = mulf %32, %33 rounding<nearest_even> : tile<2x4xf32>
    %35 = addf %26, %34 rounding<nearest_even> : tile<2x4xf32>
    %36 = reshape %arg4 : tile<f32> -> tile<1x1xf32>
    %37 = broadcast %36 : tile<1x1xf32> -> tile<2x4xf32>
    %38 = mulf %35, %37 rounding<nearest_even> : tile<2x4xf32>
    %39 = itof %arg5 signed rounding<nearest_even> : tile<i32> -> tile<f32>
    %40 = reshape %39 : tile<f32> -> tile<1x1xf32>
    %41 = broadcast %40 : tile<1x1xf32> -> tile<2x4xf32>
    %42 = addf %38, %41 rounding<nearest_even> : tile<2x4xf32>
    %43 = reshape %42 : tile<2x4xf32> -> tile<1x2x4xf32>
    %44 = assume div_by<16>, %arg3 : tile<ptr<f32>>
    %45 = make_tensor_view %44, shape = [1, 4, 4], strides = [16, 4, 1] : tensor_view<1x4x4xf32, strides=[16, 4, 1]>
    %46 = make_partition_view %45 : partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>
    %47 = store_view_tko weak %43, %46[%8, %9, %13] token=%0 : tile<1x2x4xf32>, partition_view<tile=(1x2x4), padding_value = zero, tensor_view<1x4x4xf32, strides=[16, 4, 1]>, dim_map=[0, 1, 2]>, tile<i32> -> token
    return
  }
}
