cuda_tile.module @m {
  entry @loop_until(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [128], strides = [1] : tensor_view<128xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<128xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xf64>, token
    %9 = constant <f64: 1.0> : tile<128xf64>
    %10 = constant <f64: 0.0> : tile<128xf64>
    %11, %12 = loop iter_values(%13 = %9, %14 = %10) : tile<128xf64>, tile<128xf64> -> (tile<128xf64>, tile<128xf64>) {
      %15 = mulf %13, %13 rounding<nearest_even> : tile<128xf64>
      %16 = subf %15, %7 rounding<nearest_even> : tile<128xf64>
      %17 = absf %16 : tile<128xf64>
      %18 = reduce %17 dim=0 identities=[-Infinity : f64] : tile<128xf64> -> tile<f64> (%19: tile<f64>, %20: tile<f64>) {
        %21 = maxf %19, %20 : tile<f64>
        yield %21 : tile<f64>
      }
      %22 = divf %7, %13 rounding<nearest_even> : tile<128xf64>
      %23 = addf %13, %22 rounding<nearest_even> : tile<128xf64>
      %24 = constant <f64: 0.5> : tile<128xf64>
      %25 = mulf %24, %23 rounding<nearest_even> : tile<128xf64>
      %26 = constant <f64: 1.0E-12> : tile<f64>
      %27 = cmpf greater_than ordered %26, %18 : tile<f64> -> tile<i1>
      %28 = constant <f64: 1.0> : tile<128xf64>
      %29 = addf %14, %28 rounding<nearest_even> : tile<128xf64>
      if %27 {
        break %13, %14 : tile<128xf64>, tile<128xf64>
      } else {
        yield
      }
      continue %25, %29 : tile<128xf64>, tile<128xf64>
    }
    %30 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %31 = make_tensor_view %30, shape = [256], strides = [1] : tensor_view<256xf64, strides=[1]>
    %32 = make_partition_view %31 : partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>
    %33 = constant <i32: 2> : tile<i32>
    %34 = muli %4, %33 : tile<i32>
    %35 = store_view_tko weak %11, %32[%34] token=%0 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    %36 = constant <i32: 2> : tile<i32>
    %37 = muli %4, %36 : tile<i32>
    %38 = constant <i32: 1> : tile<i32>
    %39 = addi %37, %38 : tile<i32>
    %40 = store_view_tko weak %12, %32[%39] token=%35 : tile<128xf64>, partition_view<tile=(128), padding_value = zero, tensor_view<256xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
