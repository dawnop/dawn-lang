cuda_tile.module @m {
  entry @foldif(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1, %2, %3 = get_tile_block_id : tile<i32>
    %4 = constant <i32: 4> : tile<i32>
    %5 = muli %1, %4 : tile<i32>
    %6 = constant <i32: 1> : tile<i32>
    %7 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %8 = make_tensor_view %7, shape = [1024], strides = [1] : tensor_view<1024xf64, strides=[1]>
    %9 = make_partition_view %8 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>
    %10, %11 = load_view_tko weak %9[%5] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %12 = addi %5, %6 : tile<i32>
    %13 = addi %5, %4 : tile<i32>
    %14, %15, %16 = for %17 in (%12 to %13, step %6) : tile<i32> iter_values(%18 = %10, %19 = %10, %20 = %10) -> (tile<128xf64>, tile<128xf64>, tile<128xf64>) {
      %21, %22 = load_view_tko weak %9[%17] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1024xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
      %23 = addf %18, %21 rounding<nearest_even> : tile<128xf64>
      %24 = maxf %19, %21 : tile<128xf64>
      %25 = minf %20, %21 : tile<128xf64>
      continue %23, %24, %25 : tile<128xf64>, tile<128xf64>, tile<128xf64>
    }
    %26 = constant <i32: 0> : tile<i32>
    %27 = cmpi equal %1, %26, signed : tile<i32> -> tile<i1>
    %28 = if %27 -> (tile<128xf64>) {
      yield %14 : tile<128xf64>
    } else {
      %29 = subf %15, %16 rounding<nearest_even> : tile<128xf64>
      yield %29 : tile<128xf64>
    }
    %30, %31, %32 = get_num_tile_blocks : tile<i32>
    %33 = constant <i32: 128> : tile<i32>
    %34 = muli %30, %33 : tile<i32>
    %35 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %36 = make_tensor_view %35, shape = [%34], strides = [1] : tile<i32> -> tensor_view<?xf64, strides=[1]>
    %37 = make_partition_view %36 : partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>
    %38, %39, %40 = get_tile_block_id : tile<i32>
    %41 = store_view_tko weak %28, %37[%38] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<?xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
