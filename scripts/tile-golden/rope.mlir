cuda_tile.module @m {
  entry @rope(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = constant <i32: 0> : tile<i32>
    %2 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %3 = make_tensor_view %2, shape = [96, 32], strides = [32, 1] : tensor_view<96x32xf64, strides=[32, 1]>
    %4 = make_partition_view %3 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %5, %6, %7 = get_tile_block_id : tile<i32>
    %8, %9 = load_view_tko weak %4[%5, %1] token=%0 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x16xf64>, token
    %10 = constant <i32: 1> : tile<i32>
    %11, %12 = load_view_tko weak %4[%5, %10] token=%9 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x16xf64>, token
    %13 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %14 = make_tensor_view %13, shape = [96, 32], strides = [32, 1] : tensor_view<96x32xf64, strides=[32, 1]>
    %15 = make_partition_view %14 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %16, %17 = load_view_tko weak %15[%5, %1] token=%12 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x16xf64>, token
    %18 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %19 = make_tensor_view %18, shape = [96, 32], strides = [32, 1] : tensor_view<96x32xf64, strides=[32, 1]>
    %20 = make_partition_view %19 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %21, %22 = load_view_tko weak %20[%5, %1] token=%17 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> tile<32x16xf64>, token
    %23 = mulf %8, %16 rounding<nearest_even> : tile<32x16xf64>
    %24 = mulf %11, %21 rounding<nearest_even> : tile<32x16xf64>
    %25 = subf %23, %24 rounding<nearest_even> : tile<32x16xf64>
    %26 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %27 = make_tensor_view %26, shape = [96, 32], strides = [32, 1] : tensor_view<96x32xf64, strides=[32, 1]>
    %28 = make_partition_view %27 : partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>
    %29, %30, %31 = get_tile_block_id : tile<i32>
    %32 = constant <i32: 2> : tile<i32>
    %33 = muli %30, %32 : tile<i32>
    %34 = store_view_tko weak %25, %28[%5, %33] token=%22 : tile<32x16xf64>, partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    %35 = mulf %11, %16 rounding<nearest_even> : tile<32x16xf64>
    %36 = mulf %8, %21 rounding<nearest_even> : tile<32x16xf64>
    %37 = addf %35, %36 rounding<nearest_even> : tile<32x16xf64>
    %38 = constant <i32: 2> : tile<i32>
    %39 = muli %30, %38 : tile<i32>
    %40 = constant <i32: 1> : tile<i32>
    %41 = addi %39, %40 : tile<i32>
    %42 = store_view_tko weak %37, %28[%5, %41] token=%34 : tile<32x16xf64>, partition_view<tile=(32x16), padding_value = zero, tensor_view<96x32xf64, strides=[32, 1]>, dim_map=[0, 1]>, tile<i32> -> token
    return
  }
}
