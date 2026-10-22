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
    %12, %13 = load_view_tko weak %11[%4] token=%0 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> tile<128xi32>, token
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
    %24 = constant <i32: 3> : tile<i32>
    %25 = constant <i32: 31> : tile<i32>
    %26 = andi %24, %25 : tile<i32>
    %27 = reshape %26 : tile<i32> -> tile<1xi32>
    %28 = broadcast %27 : tile<1xi32> -> tile<128xi32>
    %29 = shli %7, %28 : tile<128xi32>
    %30 = constant <i32: 5> : tile<i32>
    %31 = constant <i32: 31> : tile<i32>
    %32 = andi %30, %31 : tile<i32>
    %33 = reshape %32 : tile<i32> -> tile<1xi32>
    %34 = broadcast %33 : tile<1xi32> -> tile<128xi32>
    %35 = shri %7, %34 signed : tile<128xi32>
    %36 = constant <i32: 5> : tile<i32>
    %37 = constant <i32: 31> : tile<i32>
    %38 = andi %36, %37 : tile<i32>
    %39 = reshape %38 : tile<i32> -> tile<1xi32>
    %40 = broadcast %39 : tile<1xi32> -> tile<128xi32>
    %41 = shri %7, %40 unsigned : tile<128xi32>
    %42 = itof %7 signed rounding<nearest_even> : tile<128xi32> -> tile<128xf64>
    %43 = constant <f64: 0.5> : tile<128xf64>
    %44 = mulf %42, %43 rounding<nearest_even> : tile<128xf64>
    %45 = ftoi %44 signed rounding<nearest_int_to_zero> : tile<128xf64> -> tile<128xi32>
    %46 = trunci %7 : tile<128xi32> -> tile<128xi1>
    %47 = exti %46 unsigned : tile<128xi1> -> tile<128xi32>
    %48 = bitcast %7 : tile<128xi32> -> tile<128xf32>
    %49 = bitcast %48 : tile<128xf32> -> tile<128xi32>
    %50 = addi %16, %17 : tile<128xi32>
    %51 = xori %50, %18 : tile<128xi32>
    %52 = addi %51, %19 : tile<128xi32>
    %53 = xori %52, %20 : tile<128xi32>
    %54 = addi %53, %21 : tile<128xi32>
    %55 = xori %54, %22 : tile<128xi32>
    %56 = addi %55, %23 : tile<128xi32>
    %57 = xori %56, %29 : tile<128xi32>
    %58 = addi %57, %35 : tile<128xi32>
    %59 = xori %58, %41 : tile<128xi32>
    %60 = andi %7, %12 : tile<128xi32>
    %61 = addi %59, %60 : tile<128xi32>
    %62 = ori %7, %12 : tile<128xi32>
    %63 = xori %61, %62 : tile<128xi32>
    %64 = xori %7, %12 : tile<128xi32>
    %65 = addi %63, %64 : tile<128xi32>
    %66 = xori %65, %45 : tile<128xi32>
    %67 = addi %66, %47 : tile<128xi32>
    %68 = xori %67, %49 : tile<128xi32>
    %69 = assume div_by<16>, %arg2 : tile<ptr<i32>>
    %70 = make_tensor_view %69, shape = [1000], strides = [1] : tensor_view<1000xi32, strides=[1]>
    %71 = make_partition_view %70 : partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>
    %72 = store_view_tko weak %68, %71[%4] token=%0 : tile<128xi32>, partition_view<tile=(128), padding_value = zero, tensor_view<1000xi32, strides=[1]>, dim_map=[0]>, tile<i32> -> token
    return
  }
}
