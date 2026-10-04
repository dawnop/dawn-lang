cuda_tile.module @m {
  entry @ppo_loss(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %9 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %14 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %15 = make_tensor_view %14, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %16 = make_partition_view %15 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %17, %18 = load_view_tko weak %16[%4] token=%13 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %19 = subf %12, %17 rounding<nearest_even> : tile<1024xf64>
    %20 = exp %19 : tile<1024xf64>
    %21 = constant <f64: 0.8> : tile<1024xf64>
    %22 = maxf %20, %21 : tile<1024xf64>
    %23 = constant <f64: 1.2> : tile<1024xf64>
    %24 = minf %22, %23 : tile<1024xf64>
    %25 = mulf %20, %7 rounding<nearest_even> : tile<1024xf64>
    %26 = mulf %24, %7 rounding<nearest_even> : tile<1024xf64>
    %27 = minf %25, %26 : tile<1024xf64>
    %28, %29, %30 = get_tile_block_id : tile<i32>
    %31 = constant <i32: 1024> : tile<i32>
    %32 = muli %28, %31 : tile<i32>
    %33 = reshape %32 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<1024xi32>
    %35 = iota : tile<1024xi32>
    %36 = addi %34, %35 : tile<1024xi32>
    %37 = constant <i32: 1000> : tile<1024xi32>
    %38 = cmpi less_than %36, %37, signed : tile<1024xi32> -> tile<1024xi1>
    %39 = constant <f64: 0.0> : tile<1024xf64>
    %40 = select %38, %27, %39 : tile<1024xi1>, tile<1024xf64>
    %41 = reduce %40 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%42: tile<f64>, %43: tile<f64>) {
      %44 = addf %42, %43 rounding<nearest_even> : tile<f64>
      yield %44 : tile<f64>
    }
    %45 = constant <f64: 1000.0> : tile<f64>
    %46 = divf %41, %45 rounding<nearest_even> : tile<f64>
    %47 = negf %46 : tile<f64>
    %48 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %49 = make_tensor_view %48, shape = [1], strides = [1] : tensor_view<1xf64, strides=[1]>
    %50 = make_partition_view %49 : partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>
    %51 = reshape %47 : tile<f64> -> tile<1xf64>
    %52 = broadcast %51 : tile<1xf64> -> tile<1xf64>
    %53 = store_view_tko weak %52, %50[%4] token=%18 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
