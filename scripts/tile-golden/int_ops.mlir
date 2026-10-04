cuda_tile.module @m {
  entry @int_ops(%arg0: tile<ptr<i32>>, %arg1: tile<ptr<i32>>, %arg2: tile<ptr<i32>>) {
    %0 = make_token : token
    %1 = assume div_by<16>, %arg0 : tile<ptr<i32>>
    %2 = make_tensor_view %1, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %3 = make_partition_view %2 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %4, %5, %6 = get_tile_block_id : tile<i32>
    %7, %8 = load_view_tko weak %3[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %9 = assume div_by<16>, %arg1 : tile<ptr<i32>>
    %10 = make_tensor_view %9, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %11 = make_partition_view %10 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %12, %13 = load_view_tko weak %11[%4] token=%8 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
    %14 = constant <i32: 1> : tile<128xi32>
    %15 = ori %12, %14 : tile<128xi32>
    %16 = subi %7, %12 : tile<128xi32>
    %17 = mulhii %7, %12 : tile<128xi32>
    %18 = divi %7, %15 signed : tile<128xi32>
    %19 = remi %7, %15 signed : tile<128xi32>
    %20 = maxi %7, %12 signed : tile<128xi32>
    %21 = mini %7, %12 signed : tile<128xi32>
    %22 = negi %7 : tile<128xi32>
    %23 = absi %16 : tile<128xi32>
    %24 = constant <i32: 3> : tile<128xi32>
    %25 = shli %7, %24 : tile<128xi32>
    %26 = constant <i32: 5> : tile<128xi32>
    %27 = shri %7, %26 signed : tile<128xi32>
    %28 = constant <i32: 5> : tile<128xi32>
    %29 = shri %7, %28 unsigned : tile<128xi32>
    %30 = itof %7 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %31 = constant <f64: 0.5> : tile<128xf64>
    %32 = mulf %30, %31 rounding<nearest_even> : tile<128xf64>
    %33 = ftoi %32 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi32>
    %34 = trunci %7 : tile<128xi32> -> tile<128xi1>
    %35 = exti %34 unsigned : tile<128xi1> -> tile<128xi32>
    %36 = bitcast %7 : tile<128xi32> -> tile<128xf32>
    %37 = bitcast %36 : tile<128xf32> -> tile<128xi32>
    %38 = addi %16, %17 : tile<128xi32>
    %39 = xori %38, %18 : tile<128xi32>
    %40 = addi %39, %19 : tile<128xi32>
    %41 = xori %40, %20 : tile<128xi32>
    %42 = addi %41, %21 : tile<128xi32>
    %43 = xori %42, %22 : tile<128xi32>
    %44 = addi %43, %23 : tile<128xi32>
    %45 = xori %44, %25 : tile<128xi32>
    %46 = addi %45, %27 : tile<128xi32>
    %47 = xori %46, %29 : tile<128xi32>
    %48 = andi %7, %12 : tile<128xi32>
    %49 = addi %47, %48 : tile<128xi32>
    %50 = ori %7, %12 : tile<128xi32>
    %51 = xori %49, %50 : tile<128xi32>
    %52 = xori %7, %12 : tile<128xi32>
    %53 = addi %51, %52 : tile<128xi32>
    %54 = xori %53, %33 : tile<128xi32>
    %55 = addi %54, %35 : tile<128xi32>
    %56 = xori %55, %37 : tile<128xi32>
    %57 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %58 = make_tensor_view %57, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %59 = make_partition_view %58 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %60 = store_view_tko weak %56, %59[%4] token=%13 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
