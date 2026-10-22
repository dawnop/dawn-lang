cuda_tile.module @m {
  entry @staged_value(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9, %10, %11 = get_tile_block_id : tile<i32>
    %12 = constant <i32: 0> : tile<i32>
    %13 = cmpi equal %9, %12, signed : tile<i32> -> tile<i1>
    %14 = if %13 -> (tile<128xf64>) {
      %15 = constant <f64: 2.0> : tile<128xf64>
      %16 = addf %7, %15 rounding<nearest_even> : tile<128xf64>
      yield %16 : tile<128xf64>
    } else {
      %17 = constant <i32: 1> : tile<i32>
      %18 = cmpi equal %9, %17, signed : tile<i32> -> tile<i1>
      %19 = if %18 -> (tile<128xf64>) {
        %20 = constant <f64: 3.0> : tile<128xf64>
        %21 = mulf %7, %20 rounding<nearest_even> : tile<128xf64>
        yield %21 : tile<128xf64>
      } else {
        %22 = constant <f64: 5.0> : tile<128xf64>
        %23 = subf %7, %22 rounding<nearest_even> : tile<128xf64>
        yield %23 : tile<128xf64>
      }
      yield %19 : tile<128xf64>
    }
    %24 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %25 = make_tensor_view %24, shape = [512], strides = [1] : tensor_view<512xf64, strides=[1]>
    %26 = make_partition_view %25 : partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>
    %27 = store_view_tko weak %14, %26[%4] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<512xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
