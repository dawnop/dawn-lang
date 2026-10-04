cuda_tile.module @m {
  entry @dpo_loss(%arg0: tile<ptr<f64>>, %arg1: tile<ptr<f64>>, %arg2: tile<ptr<f64>>, %arg3: tile<ptr<f64>>, %arg4: tile<ptr<f64>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<f64>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<f64>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %14 = subf %7, %12 rounding<nearest_even> : tile<1024xf64>
    %15 = assume div_by<16>, %arg2 : tile<ptr<f64>>
    %16 = make_tensor_view %15, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %17 = make_partition_view %16 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %18, %19 = load_view_tko weak %17[%4] token=%13 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %20 = assume div_by<16>, %arg3 : tile<ptr<f64>>
    %21 = make_tensor_view %20, shape = [1000], strides = [1] : tensor_view<1000xf64, strides=[1]>
    %22 = make_partition_view %21 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>
    %23, %24 = load_view_tko weak %22[%4] token=%19 : partition_view<tile=(1024), padding_value = zero, tensor_view<1000xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<1024xf64>, token
    %25 = subf %18, %23 rounding<nearest_even> : tile<1024xf64>
    %26 = subf %14, %25 rounding<nearest_even> : tile<1024xf64>
    %27 = constant <f64: 0.1> : tile<1024xf64>
    %28 = mulf %27, %26 rounding<nearest_even> : tile<1024xf64>
    %29 = negf %28 : tile<1024xf64>
    %30 = exp %29 : tile<1024xf64>
    %31 = constant <f64: 1.0> : tile<1024xf64>
    %32 = addf %31, %30 rounding<nearest_even> : tile<1024xf64>
    %33 = divf %31, %32 rounding<nearest_even> : tile<1024xf64>
    %34, %35, %36 = get_tile_block_id : tile<i32>
    %37 = constant <i32: 1024> : tile<i32>
    %38 = muli %34, %37 : tile<i32>
    %39 = reshape %38 : tile<i32> -> tile<1xi32>
    %40 = broadcast %39 : tile<1xi32> -> tile<1024xi32>
    %41 = iota : tile<1024xi32>
    %42 = addi %40, %41 : tile<1024xi32>
    %43 = constant <i32: 1000> : tile<1024xi32>
    %44 = cmpi less_than %42, %43, signed : tile<1024xi32> -> tile<1024xi1>
    %45 = log %33 : tile<1024xf64>
    %46 = constant <f64: 0.0> : tile<1024xf64>
    %47 = select %44, %45, %46 : tile<1024xi1>, tile<1024xf64>
    %48 = reduce %47 dim=0 identities=[0.0 : f64] : tile<1024xf64> -> tile<f64> (%49: tile<f64>, %50: tile<f64>) {
      %51 = addf %49, %50 rounding<nearest_even> : tile<f64>
      yield %51 : tile<f64>
    }
    %52 = constant <f64: 1000.0> : tile<f64>
    %53 = divf %48, %52 rounding<nearest_even> : tile<f64>
    %54 = negf %53 : tile<f64>
    %55 = assume div_by<16>, %arg4 : tile<ptr<f64>>
    %56 = make_tensor_view %55, shape = [1], strides = [1] : tensor_view<1xf64, strides=[1]>
    %57 = make_partition_view %56 : partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>
    %58 = reshape %54 : tile<f64> -> tile<1xf64>
    %59 = broadcast %58 : tile<1xf64> -> tile<1xf64>
    %60 = store_view_tko weak %59, %57[%4] token=%24 : tile<1xf64>, partition_view<tile=(1), padding_value = zero, tensor_view<1xf64, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
